from collections.abc import Iterator
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import psycopg
import pytest
from psycopg.rows import TupleRow

from rag_ingestion.domain.collection import Collection
from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.doc_type import DocType
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.document_status import DocumentStatus
from rag_ingestion.domain.metadata import Metadata
from rag_ingestion.infrastructure.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from rag_ingestion.infrastructure.postgres.document_repository import (
    PostgresDocumentRepository,
)

pytestmark = pytest.mark.integration

type Connection = psycopg.Connection[TupleRow]

_CONTENT = b"FastAPI dependency injection, explained at length."
_INGESTED_AT = datetime(2026, 9, 12, 10, 30, tzinfo=UTC)

if TYPE_CHECKING:
    # Not a runtime test: `mypy --strict` is the assertion. The ports are
    # `Protocol`s, so nothing at runtime forces these classes to match them and
    # a drifted signature would otherwise be found by a failing query. Naming
    # the protocol types here makes the type checker prove conformance instead.
    from rag_ingestion.domain.ports import CollectionRepository, DocumentRepository

    def _ports_are_satisfied(
        documents: PostgresDocumentRepository,
        collections: PostgresCollectionRepository,
    ) -> tuple[DocumentRepository, CollectionRepository]:
        return documents, collections


@pytest.fixture
def documents(migrated: Connection) -> PostgresDocumentRepository:
    return PostgresDocumentRepository(migrated)


@pytest.fixture
def collections(migrated: Connection) -> PostgresCollectionRepository:
    return PostgresCollectionRepository(migrated)


@pytest.fixture
def collection(collections: PostgresCollectionRepository) -> Collection:
    stored = Collection(collection_id=CollectionId.generate(), name="fastapi-docs")
    collections.add(stored)
    return stored


def _document(
    collection_id: CollectionId,
    *,
    content: bytes = _CONTENT,
    library_version: str | None = "0.115.0",
    source_url: str | None = "https://fastapi.tiangolo.com/tutorial/",
) -> Document:
    return Document(
        document_id=DocumentId.generate(),
        collection_id=collection_id,
        content_hash=ContentHash.of(content),
        size_in_bytes=len(content),
        metadata=Metadata(
            source_library="fastapi",
            doc_type=DocType.TUTORIAL,
            library_version=library_version,
            source_url=source_url,
        ),
        ingested_at=_INGESTED_AT,
    )


class TestCollections:
    def test_a_stored_collection_comes_back(
        self, collections: PostgresCollectionRepository
    ) -> None:
        stored = Collection(collection_id=CollectionId.generate(), name="pydantic-docs")
        collections.add(stored)

        retrieved = collections.get(stored.collection_id)

        assert retrieved is not None
        # Field by field, because `Collection.__eq__` compares identity alone:
        # `retrieved == stored` would hold even if the name came back wrong.
        assert retrieved.collection_id == stored.collection_id
        assert retrieved.name == "pydantic-docs"

    def test_an_unknown_collection_is_none(
        self, collections: PostgresCollectionRepository
    ) -> None:
        assert collections.get(CollectionId.generate()) is None

    def test_a_name_is_not_taken_until_it_is_stored(
        self, collections: PostgresCollectionRepository
    ) -> None:
        assert collections.exists_with_name("qdrant-docs") is False

        collections.add(
            Collection(collection_id=CollectionId.generate(), name="qdrant-docs")
        )

        assert collections.exists_with_name("qdrant-docs") is True

    def test_names_differing_only_in_case_are_different_names(
        self, collections: PostgresCollectionRepository
    ) -> None:
        collections.add(
            Collection(collection_id=CollectionId.generate(), name="Redis-Docs")
        )

        # `Collection` strips but does not fold case, so the adapter must not
        # either. Folding here would enforce a rule the domain does not have.
        assert collections.exists_with_name("redis-docs") is False


class TestDocuments:
    def test_every_field_survives_the_round_trip(
        self, documents: PostgresDocumentRepository, collection: Collection
    ) -> None:
        stored = _document(collection.collection_id)
        documents.add(stored, _CONTENT)

        retrieved = documents.get(stored.document_id)

        assert retrieved is not None
        assert retrieved.document_id == stored.document_id
        assert retrieved.collection_id == collection.collection_id
        assert retrieved.content_hash == ContentHash.of(_CONTENT)
        assert retrieved.size_in_bytes == len(_CONTENT)
        assert retrieved.status is DocumentStatus.PENDING
        assert retrieved.ingested_at == _INGESTED_AT
        assert retrieved.metadata.source_library == "fastapi"
        assert retrieved.metadata.doc_type is DocType.TUTORIAL
        # These two are both nullable text and adjacent in the column list, so
        # they are given distinguishable values on purpose: swapping them is a
        # mistake `mypy` cannot see, because a row element is typed `Any`.
        assert retrieved.metadata.library_version == "0.115.0"
        assert retrieved.metadata.source_url == "https://fastapi.tiangolo.com/tutorial/"

    def test_absent_optional_metadata_comes_back_absent(
        self, documents: PostgresDocumentRepository, collection: Collection
    ) -> None:
        stored = _document(
            collection.collection_id, library_version=None, source_url=None
        )
        documents.add(stored, _CONTENT)

        retrieved = documents.get(stored.document_id)

        assert retrieved is not None
        assert retrieved.metadata.library_version is None
        assert retrieved.metadata.source_url is None

    def test_a_status_that_is_not_the_default_round_trips(
        self, documents: PostgresDocumentRepository, collection: Collection
    ) -> None:
        stored = _document(collection.collection_id)
        stored.start_processing()

        documents.add(stored, _CONTENT)
        retrieved = documents.get(stored.document_id)

        assert retrieved is not None
        assert retrieved.status is DocumentStatus.PROCESSING

    def test_an_unknown_document_is_none(
        self, documents: PostgresDocumentRepository
    ) -> None:
        assert documents.get(DocumentId.generate()) is None

    def test_the_content_is_stored_even_though_get_does_not_return_it(
        self,
        documents: PostgresDocumentRepository,
        collection: Collection,
        migrated: Connection,
    ) -> None:
        stored = _document(collection.collection_id)
        documents.add(stored, _CONTENT)

        row = migrated.execute(
            "SELECT content FROM documents WHERE document_id = %s",
            (stored.document_id.value,),
        ).fetchone()

        assert row is not None
        assert bytes(row[0]) == _CONTENT

    def test_content_is_not_present_until_it_is_stored(
        self, documents: PostgresDocumentRepository, collection: Collection
    ) -> None:
        content_hash = ContentHash.of(_CONTENT)

        assert (
            documents.exists_with_content_hash(collection.collection_id, content_hash)
            is False
        )

        documents.add(_document(collection.collection_id), _CONTENT)

        assert (
            documents.exists_with_content_hash(collection.collection_id, content_hash)
            is True
        )

    def test_a_failed_document_does_not_make_its_content_present(
        self, documents: PostgresDocumentRepository, collection: Collection
    ) -> None:
        failed = _document(collection.collection_id)
        failed.start_processing()
        failed.mark_failed()

        documents.add(failed, _CONTENT)

        # The port's contract, now proved through the adapter rather than a
        # fake: the resubmission `Document.mark_failed` promises stays possible.
        assert (
            documents.exists_with_content_hash(
                collection.collection_id, ContentHash.of(_CONTENT)
            )
            is False
        )

    def test_the_same_content_in_another_collection_is_not_present(
        self,
        documents: PostgresDocumentRepository,
        collections: PostgresCollectionRepository,
        collection: Collection,
    ) -> None:
        other = Collection(collection_id=CollectionId.generate(), name="other-docs")
        collections.add(other)
        documents.add(_document(collection.collection_id), _CONTENT)

        assert (
            documents.exists_with_content_hash(
                other.collection_id, ContentHash.of(_CONTENT)
            )
            is False
        )

    def test_counting_an_empty_collection(
        self, documents: PostgresDocumentRepository, collection: Collection
    ) -> None:
        assert documents.count_in_collection(collection.collection_id) == 0

    def test_a_failed_document_still_counts_towards_the_collection(
        self, documents: PostgresDocumentRepository, collection: Collection
    ) -> None:
        failed = _document(collection.collection_id, content=b"one")
        failed.start_processing()
        failed.mark_failed()
        documents.add(failed, b"one")
        documents.add(_document(collection.collection_id, content=b"two"), b"two")

        # `count_in_collection` says "currently holds", and a failed row still
        # occupies the collection. This is the half of the rule that differs
        # from deduplication, and the reason the schema needs both indexes.
        assert documents.count_in_collection(collection.collection_id) == 2

    def test_counting_is_per_collection(
        self,
        documents: PostgresDocumentRepository,
        collections: PostgresCollectionRepository,
        collection: Collection,
    ) -> None:
        other = Collection(collection_id=CollectionId.generate(), name="other-docs")
        collections.add(other)
        documents.add(_document(collection.collection_id, content=b"here"), b"here")

        assert documents.count_in_collection(other.collection_id) == 0


class TestTheTransactionBelongsToTheCaller:
    """The design claim that makes 4.2 possible, proved rather than asserted.

    If either repository committed on its own, a rollback would not undo its
    work and the outbox row could not share the document's transaction. These
    tests fail the moment a `commit()` appears in an adapter.
    """

    @pytest.fixture
    def caller(self, migrated: Connection, postgres_url: str) -> Iterator[Connection]:
        # A second connection, deliberately NOT autocommit, so that this test
        # owns the transaction boundary the way the composition root will.
        with psycopg.connect(postgres_url) as connection:
            yield connection
            connection.rollback()

    def test_a_rollback_undoes_what_the_repositories_wrote(
        self, caller: Connection, migrated: Connection
    ) -> None:
        collections = PostgresCollectionRepository(caller)
        documents = PostgresDocumentRepository(caller)
        stored = Collection(collection_id=CollectionId.generate(), name="rolled-back")
        collections.add(stored)
        document = _document(stored.collection_id)
        documents.add(document, _CONTENT)

        caller.rollback()

        # Asked on a different connection, so this is what durably happened.
        assert PostgresCollectionRepository(migrated).get(stored.collection_id) is None
        assert PostgresDocumentRepository(migrated).get(document.document_id) is None

    def test_two_repositories_on_one_connection_are_one_transaction(
        self, caller: Connection, migrated: Connection
    ) -> None:
        collections = PostgresCollectionRepository(caller)
        documents = PostgresDocumentRepository(caller)
        stored = Collection(collection_id=CollectionId.generate(), name="committed")
        collections.add(stored)
        document = _document(stored.collection_id)
        documents.add(document, _CONTENT)

        caller.commit()

        # Both, from one commit the caller issued — which is exactly what 4.2
        # needs in order to put the outbox row in with them.
        assert (
            PostgresCollectionRepository(migrated).get(stored.collection_id) is not None
        )
        assert (
            PostgresDocumentRepository(migrated).get(document.document_id) is not None
        )
