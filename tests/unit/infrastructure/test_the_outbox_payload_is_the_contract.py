"""What the outbox publisher writes is `rag_contracts`' `DocumentIngested`.

The pure half of the claim, with no database: `_as_payload` is a function from
the domain's event to JSON, so it can be held to the contract without a
container. The half that needs one, that the row *read back from PostgreSQL*
still validates, is in `tests/integration/test_outbox_publisher.py`. ADR 0026.
"""

import json
from datetime import UTC, datetime, timedelta, timezone

import pytest
from rag_contracts.events import EVENT_TYPE, STREAM_NAME
from rag_contracts.events import DocumentIngested as Contract

from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.doc_type import DocType
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.events import DocumentIngested
from rag_ingestion.domain.metadata import Metadata
from rag_ingestion.infrastructure.postgres.outbox_event_publisher import _as_payload

_AT = datetime(2026, 9, 12, 11, 45, tzinfo=UTC)


def _event(
    metadata: Metadata | None = None, occurred_at: datetime = _AT
) -> DocumentIngested:
    return DocumentIngested(
        document_id=DocumentId.generate(),
        collection_id=CollectionId.generate(),
        content_hash=ContentHash.of(b"FastAPI runs a def endpoint in a threadpool."),
        metadata=metadata
        or Metadata(source_library="fastapi", doc_type=DocType.TUTORIAL),
        occurred_at=occurred_at,
    )


class TestEveryDomainValueIsOneTheContractAccepts:
    """The two definitions of the metadata rules, held against each other.

    The contract states `doc_type` as a pattern and the domain as a closed set of
    values. They agree today; this is the test that fails the day a value is
    added to one and the pattern does not admit it.
    """

    @pytest.mark.parametrize("doc_type", list(DocType))
    def test_every_doc_type_the_domain_has_passes_the_contract(
        self, doc_type: DocType
    ) -> None:
        event = _event(Metadata(source_library="uv", doc_type=doc_type))

        payload = _as_payload(event)

        assert payload["metadata"]["doc_type"] == doc_type.value
        assert Contract.model_validate(payload).metadata.doc_type == doc_type.value

    def test_a_fully_populated_event_passes_the_contract(self) -> None:
        event = _event(
            Metadata(
                source_library="qdrant",
                doc_type=DocType.API_REFERENCE,
                library_version="1.14",
                source_url="https://qdrant.tech/documentation/concepts/points/",
            )
        )

        contract = Contract.model_validate(_as_payload(event))

        assert contract.metadata.library_version == "1.14"
        assert contract.metadata.source_url == (
            "https://qdrant.tech/documentation/concepts/points/"
        )


class TestTheContractIsNeverStricterThanTheDomain:
    """A document the domain stored must never be refused at the outbox.

    If the contract rejected something the domain accepted, ingestion would write
    the document and then fail to announce it, and fail again on every retry: a
    permanent 500 for an input that used to work. These are the inputs that
    exposed it, each one valid by the domain's rule (`urlparse`, an http or https
    scheme, a host). ADR 0026.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "HTTPS://Docs.Example.com/A",
            "https://example.com/a b",
            "http://exa\tmple.com/x",
            "https://example.com/caf\u00e9",
            "https://example.com/?q=1#frag",
        ],
    )
    def test_a_source_url_the_domain_accepts_reaches_the_payload_unchanged(
        self, url: str
    ) -> None:
        metadata = Metadata(
            source_library="uv", doc_type=DocType.CLI_REFERENCE, source_url=url
        )

        payload = _as_payload(_event(metadata))

        assert payload["metadata"]["source_url"] == metadata.source_url


class TestTheShapeOnTheWire:
    def test_the_payload_round_trips_to_the_domain_values(self) -> None:
        event = _event()

        contract = Contract.model_validate(_as_payload(event))

        assert contract.document_id == event.document_id.value
        assert contract.collection_id == event.collection_id.value
        assert contract.content_hash == str(event.content_hash)
        assert contract.occurred_at == event.occurred_at

    def test_the_version_is_written_not_left_to_the_default(self) -> None:
        assert _as_payload(_event())["schema_version"] == 1

    def test_absent_optional_metadata_is_null_and_present(self) -> None:
        metadata = _as_payload(_event())["metadata"]

        assert metadata["library_version"] is None
        assert metadata["source_url"] is None

    def test_the_payload_is_plain_json(self) -> None:
        # `Jsonb` refuses a UUID or a datetime; this would fail at the first insert.
        assert json.loads(json.dumps(_as_payload(_event())))

    def test_the_event_type_and_stream_are_the_contracts_constants(self) -> None:
        assert EVENT_TYPE == "DocumentIngested"
        assert STREAM_NAME == "documents.events"


class TestTheInstant:
    def test_it_is_written_in_utc_with_a_z(self) -> None:
        assert _as_payload(_event())["occurred_at"] == "2026-09-12T11:45:00Z"

    def test_an_instant_with_another_offset_is_written_in_utc(self) -> None:
        madrid = timezone(timedelta(hours=2))

        payload = _as_payload(
            _event(occurred_at=datetime(2026, 9, 12, 13, 45, tzinfo=madrid))
        )

        assert payload["occurred_at"] == "2026-09-12T11:45:00Z"

    def test_microseconds_survive(self) -> None:
        at = datetime(2026, 9, 12, 11, 45, 3, 105557, tzinfo=UTC)

        assert _as_payload(_event(occurred_at=at))["occurred_at"] == (
            "2026-09-12T11:45:03.105557Z"
        )
