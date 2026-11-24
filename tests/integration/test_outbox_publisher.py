from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import psycopg
import pytest
from psycopg.rows import TupleRow
from pydantic import ValidationError
from rag_contracts.events import EVENT_TYPE
from rag_contracts.events import DocumentIngested as DocumentIngestedContract

from rag_ingestion.application.ingest_document import (
    IngestDocument,
    IngestDocumentCommand,
)
from rag_ingestion.domain.collection import Collection
from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.doc_type import DocType
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.events import DocumentIngested
from rag_ingestion.domain.metadata import Metadata
from rag_ingestion.infrastructure.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from rag_ingestion.infrastructure.postgres.document_repository import (
    PostgresDocumentRepository,
)
from rag_ingestion.infrastructure.postgres.outbox_event_publisher import (
    PostgresOutboxEventPublisher,
)

pytestmark = pytest.mark.integration

type Connection = psycopg.Connection[TupleRow]

_CONTENT = b"Redis Streams as an at-least-once transport."
_OCCURRED_AT = datetime(2026, 9, 12, 11, 45, tzinfo=UTC)
_METADATA = Metadata(
    source_library="redis",
    doc_type=DocType.EXPLANATION,
    library_version="7.4",
    source_url="https://redis.io/docs/latest/develop/data-types/streams/",
)

if TYPE_CHECKING:
    # `mypy --strict` is the assertion; `EventPublisher` is a Protocol, so
    # nothing at runtime makes this class satisfy it.
    from rag_ingestion.domain.ports import EventPublisher

    def _port_is_satisfied(
        publisher: PostgresOutboxEventPublisher,
    ) -> EventPublisher:
        return publisher


@dataclass(frozen=True, slots=True)
class FixedClock:
    """The instant the test names, so `occurred_at` is an equality not a guess."""

    instant: datetime

    def now(self) -> datetime:
        return self.instant


def _event(collection_id: CollectionId, content: bytes = _CONTENT) -> DocumentIngested:
    return DocumentIngested.about(
        Document(
            document_id=DocumentId.generate(),
            collection_id=collection_id,
            content_hash=ContentHash.of(content),
            size_in_bytes=len(content),
            metadata=_METADATA,
            ingested_at=_OCCURRED_AT,
        )
    )


def _outbox_rows(connection: Connection) -> list[tuple[Any, ...]]:
    return connection.execute(
        "SELECT outbox_id, event_type, payload, occurred_at, published_at"
        " FROM outbox ORDER BY outbox_id"
    ).fetchall()


class TestWhatPublishWrites:
    @pytest.fixture
    def publisher(self, migrated: Connection) -> PostgresOutboxEventPublisher:
        return PostgresOutboxEventPublisher(migrated)

    def test_one_event_becomes_one_unpublished_row(
        self, publisher: PostgresOutboxEventPublisher, migrated: Connection
    ) -> None:
        publisher.publish(_event(CollectionId.generate()))

        rows = _outbox_rows(migrated)

        assert len(rows) == 1
        assert rows[0][1] == "DocumentIngested"
        assert rows[0][3] == _OCCURRED_AT
        # Absent, not false: the relay has not sent it, and absence is how the
        # partial index finds the backlog.
        assert rows[0][4] is None

    def test_the_payload_carries_every_field_of_the_event(
        self, publisher: PostgresOutboxEventPublisher, migrated: Connection
    ) -> None:
        event = _event(CollectionId.generate())

        publisher.publish(event)

        payload = _outbox_rows(migrated)[0][2]
        assert payload == {
            "schema_version": 1,
            "document_id": str(event.document_id),
            "collection_id": str(event.collection_id),
            "content_hash": str(event.content_hash),
            # UTC with a `Z`: the contract's spelling, not `isoformat()`'s.
            "occurred_at": "2026-09-12T11:45:00Z",
            "metadata": {
                "source_library": "redis",
                "doc_type": "explanation",
                "library_version": "7.4",
                "source_url": (
                    "https://redis.io/docs/latest/develop/data-types/streams/"
                ),
            },
        }

    def test_the_row_read_back_from_postgresql_is_a_valid_contract_event(
        self, publisher: PostgresOutboxEventPublisher, migrated: Connection
    ) -> None:
        """The check the unit suite cannot make: what PostgreSQL gives back.

        `jsonb` normalises what it stores, so a payload that validates going in
        is not thereby one that validates coming out. A consumer only ever sees
        the second. This passes the row's own `event_type` and `payload`, read
        from the table, through the schema both services install.
        """
        event = _event(CollectionId.generate())

        publisher.publish(event)

        _, event_type, payload, _, _ = _outbox_rows(migrated)[0]
        assert event_type == EVENT_TYPE
        contract = DocumentIngestedContract.model_validate(payload)
        assert contract.document_id == event.document_id.value
        assert contract.occurred_at == event.occurred_at

    def test_absent_optional_metadata_is_null_in_the_payload(
        self, publisher: PostgresOutboxEventPublisher, migrated: Connection
    ) -> None:
        bare = Metadata(source_library="uv", doc_type=DocType.CLI_REFERENCE)
        publisher.publish(
            DocumentIngested(
                document_id=DocumentId.generate(),
                collection_id=CollectionId.generate(),
                content_hash=ContentHash.of(_CONTENT),
                metadata=bare,
                occurred_at=_OCCURRED_AT,
            )
        )

        metadata = _outbox_rows(migrated)[0][2]["metadata"]

        # Present and null, rather than missing: a consumer reading the contract
        # should not have to distinguish "no version" from "key forgotten".
        assert metadata["library_version"] is None
        assert metadata["source_url"] is None

    def test_rows_are_ordered_by_the_identity_the_database_assigns(
        self, publisher: PostgresOutboxEventPublisher, migrated: Connection
    ) -> None:
        collection_id = CollectionId.generate()
        first = _event(collection_id, b"first")
        second = _event(collection_id, b"second")

        publisher.publish(first)
        publisher.publish(second)

        rows = _outbox_rows(migrated)
        assert [row[2]["document_id"] for row in rows] == [
            str(first.document_id),
            str(second.document_id),
        ]
        assert rows[0][0] < rows[1][0]


class TestTheDocumentAndItsOutboxRowAreAtomic:
    """The single most important invariant in the service, proved end to end.

    Not through the adapters in isolation but through the real `IngestDocument`,
    because the claim is about what happens when the use case runs: the document
    and the announcement either both survive or neither does.
    """

    @pytest.fixture
    def caller(self, migrated: Connection, postgres_url: str) -> Iterator[Connection]:
        # NOT autocommit. This connection plays the part the composition root
        # will play in 4.5: it owns the transaction and decides when it ends.
        with psycopg.connect(postgres_url) as connection:
            yield connection
            connection.rollback()

    @pytest.fixture
    def collection_id(self, caller: Connection) -> CollectionId:
        collection = Collection(
            collection_id=CollectionId.generate(), name="redis-docs"
        )
        PostgresCollectionRepository(caller).add(collection)
        caller.commit()
        return collection.collection_id

    @pytest.fixture
    def ingest(self, caller: Connection) -> IngestDocument:
        # All three adapters on ONE connection. That is the whole mechanism.
        return IngestDocument(
            documents=PostgresDocumentRepository(caller),
            collections=PostgresCollectionRepository(caller),
            events=PostgresOutboxEventPublisher(caller),
            clock=FixedClock(_OCCURRED_AT),
        )

    def test_one_commit_makes_both_durable(
        self,
        ingest: IngestDocument,
        caller: Connection,
        migrated: Connection,
        collection_id: CollectionId,
    ) -> None:
        document_id = ingest.execute(
            IngestDocumentCommand(
                collection_id=collection_id, content=_CONTENT, metadata=_METADATA
            )
        )

        caller.commit()

        # Both asked on a different connection, so this is what durably happened.
        assert PostgresDocumentRepository(migrated).get(document_id) is not None
        rows = _outbox_rows(migrated)
        assert len(rows) == 1
        assert rows[0][2]["document_id"] == str(document_id)

    def test_a_rollback_loses_both(
        self,
        ingest: IngestDocument,
        caller: Connection,
        migrated: Connection,
        collection_id: CollectionId,
    ) -> None:
        document_id = ingest.execute(
            IngestDocumentCommand(
                collection_id=collection_id, content=_CONTENT, metadata=_METADATA
            )
        )

        caller.rollback()

        assert PostgresDocumentRepository(migrated).get(document_id) is None
        assert _outbox_rows(migrated) == []

    def test_an_event_the_contract_refuses_loses_the_document_too(
        self,
        ingest: IngestDocument,
        caller: Connection,
        migrated: Connection,
        collection_id: CollectionId,
    ) -> None:
        """The contract's own refusal, inside the transaction, undoes the document.

        `_as_payload` validates against `rag_contracts` before the outbox INSERT,
        after the document row is already written. If that refusal left the
        document behind, there would be a stored document nobody was told about:
        the one thing this service must not do. The domain and the contract are
        meant to agree, so a refusal is reached by corrupting a `Metadata` after
        it was validated, which is how a disagreement between them would look.
        """
        disagreeing = Metadata(source_library="redis", doc_type=DocType.EXPLANATION)
        object.__setattr__(disagreeing, "source_library", "   ")

        with pytest.raises(ValidationError):
            ingest.execute(
                IngestDocumentCommand(
                    collection_id=collection_id,
                    content=_CONTENT,
                    metadata=disagreeing,
                )
            )

        # Not vacuous: the document really had been written before the refusal.
        # This is the same connection, so it sees its own uncommitted row.
        assert caller.execute("SELECT count(*) FROM documents").fetchone() == (1,)
        caller.rollback()
        assert migrated.execute("SELECT count(*) FROM documents").fetchone() == (0,)
        assert _outbox_rows(migrated) == []

    def test_a_database_error_after_the_announcement_loses_both(
        self,
        ingest: IngestDocument,
        caller: Connection,
        migrated: Connection,
        collection_id: CollectionId,
    ) -> None:
        """The failure the outbox exists for, caused by a real integrity error.

        A second write of the same content is refused by the partial unique
        index — the race ADR 0013 describes, reached here by going around the
        policy that would normally catch it. PostgreSQL aborts the transaction,
        and the document and its announcement go down together. A stored
        document nobody was told about is not reachable from here.
        """
        document_id = ingest.execute(
            IngestDocumentCommand(
                collection_id=collection_id, content=_CONTENT, metadata=_METADATA
            )
        )
        duplicate = Document(
            document_id=DocumentId.generate(),
            collection_id=collection_id,
            content_hash=ContentHash.of(_CONTENT),
            size_in_bytes=len(_CONTENT),
            metadata=_METADATA,
            ingested_at=_OCCURRED_AT,
        )

        with pytest.raises(psycopg.errors.UniqueViolation):
            PostgresDocumentRepository(caller).add(duplicate, _CONTENT)

        caller.rollback()
        assert PostgresDocumentRepository(migrated).get(document_id) is None
        assert _outbox_rows(migrated) == []
