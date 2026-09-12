"""The HTTP layer over fakes, with no infrastructure present.

Unit tests, not integration ones, and that classification is the point:
`docs/BUILD-PLAN.md` keeps the web layer talking only to the use cases until
4.5, so if these needed a container the layering would already be wrong.
"""

import base64
import inspect
from collections.abc import Iterator
from datetime import UTC, datetime
from http import HTTPStatus
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from rag_ingestion.api import dependencies
from rag_ingestion.api.app import create_app
from rag_ingestion.application.create_collection import CreateCollection
from rag_ingestion.application.get_ingestion_status import GetIngestionStatus
from rag_ingestion.application.ingest_document import IngestDocument
from rag_ingestion.domain.collection import Collection
from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.document_status import DocumentStatus
from rag_ingestion.domain.events import DocumentIngested
from rag_ingestion.domain.ingestion_policy import IngestionPolicy
from rag_ingestion.domain.limits import IngestionLimits

INGESTED_AT = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)
CONTENT = b"FastAPI runs a def endpoint in a threadpool."


class InMemoryDocumentRepository:
    def __init__(self) -> None:
        self.documents: dict[DocumentId, Document] = {}
        self.content: dict[DocumentId, bytes] = {}

    def add(self, document: Document, content: bytes) -> None:
        self.documents[document.document_id] = document
        self.content[document.document_id] = content

    def get(self, document_id: DocumentId) -> Document | None:
        return self.documents.get(document_id)

    def exists_with_content_hash(
        self, collection_id: CollectionId, content_hash: ContentHash
    ) -> bool:
        return any(
            document.collection_id == collection_id
            and document.content_hash == content_hash
            and document.status is not DocumentStatus.FAILED
            for document in self.documents.values()
        )

    def count_in_collection(self, collection_id: CollectionId) -> int:
        return sum(
            document.collection_id == collection_id
            for document in self.documents.values()
        )


class InMemoryCollectionRepository:
    def __init__(self) -> None:
        self.collections: dict[CollectionId, Collection] = {}

    def add(self, collection: Collection) -> None:
        self.collections[collection.collection_id] = collection

    def get(self, collection_id: CollectionId) -> Collection | None:
        return self.collections.get(collection_id)

    def exists_with_name(self, name: str) -> bool:
        return any(collection.name == name for collection in self.collections.values())


class RecordingEventPublisher:
    def __init__(self) -> None:
        self.published: list[DocumentIngested] = []

    def publish(self, event: DocumentIngested) -> None:
        self.published.append(event)


class FixedClock:
    def __init__(self, instant: datetime) -> None:
        self.instant = instant

    def now(self) -> datetime:
        return self.instant


class Service:
    """The three use cases over one set of doubles, wired as 4.5 will wire them."""

    def __init__(self, policy: IngestionPolicy | None = None) -> None:
        self.documents = InMemoryDocumentRepository()
        self.collections = InMemoryCollectionRepository()
        self.events = RecordingEventPublisher()
        self.ingest = IngestDocument(
            documents=self.documents,
            collections=self.collections,
            events=self.events,
            clock=FixedClock(INGESTED_AT),
            policy=policy or IngestionPolicy(),
        )
        self.create = CreateCollection(collections=self.collections)
        self.status = GetIngestionStatus(documents=self.documents)


def _app_for(service: Service) -> FastAPI:
    app = create_app()
    app.dependency_overrides[dependencies.ingest_document] = lambda: service.ingest
    app.dependency_overrides[dependencies.create_collection] = lambda: service.create
    app.dependency_overrides[dependencies.get_ingestion_status] = lambda: service.status
    return app


@pytest.fixture
def service() -> Service:
    return Service()


@pytest.fixture
def client(service: Service) -> Iterator[TestClient]:
    with TestClient(_app_for(service)) as test_client:
        yield test_client


def _body(content: bytes = CONTENT, **metadata: object) -> dict[str, object]:
    return {
        "content": base64.b64encode(content).decode(),
        "metadata": {
            "source_library": "fastapi",
            "doc_type": "tutorial",
            **metadata,
        },
    }


def _a_collection(client: TestClient, name: str = "fastapi-docs") -> str:
    response = client.post("/collections", json={"name": name})
    assert response.status_code == HTTPStatus.CREATED
    collection_id = response.json()["collection_id"]
    assert isinstance(collection_id, str)
    return collection_id


class TestCreatingACollection:
    def test_a_created_collection_returns_its_identity(
        self, client: TestClient
    ) -> None:
        response = client.post("/collections", json={"name": "pydantic-docs"})

        assert response.status_code == HTTPStatus.CREATED
        assert response.json().keys() == {"collection_id"}

    def test_a_repeated_name_is_a_conflict(self, client: TestClient) -> None:
        _a_collection(client, "qdrant-docs")

        response = client.post("/collections", json={"name": "qdrant-docs"})

        assert response.status_code == HTTPStatus.CONFLICT
        assert response.json()["code"] == "duplicate_collection_name"

    def test_a_blank_name_is_unprocessable(self, client: TestClient) -> None:
        response = client.post("/collections", json={"name": "   "})

        # The domain refuses it, not a Pydantic validator. One rule, one place.
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert response.json()["code"] == "missing_collection_name"

    def test_an_unexpected_field_is_refused(self, client: TestClient) -> None:
        response = client.post(
            "/collections", json={"name": "uv-docs", "owner": "carlos"}
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


class TestSubmittingADocument:
    def test_an_accepted_document_returns_its_identity(
        self, client: TestClient
    ) -> None:
        collection_id = _a_collection(client)

        response = client.post(f"/collections/{collection_id}/documents", json=_body())

        # 202, not 201: the document is recorded, not indexed.
        assert response.status_code == HTTPStatus.ACCEPTED
        assert response.json().keys() == {"document_id"}

    def test_the_content_arrives_decoded(
        self, client: TestClient, service: Service
    ) -> None:
        collection_id = _a_collection(client)

        client.post(f"/collections/{collection_id}/documents", json=_body())

        # Proves the base64 round trip rather than assuming it: the use case was
        # handed the original bytes, not the encoded string.
        assert list(service.documents.content.values()) == [CONTENT]

    def test_an_unknown_collection_is_not_found(self, client: TestClient) -> None:
        response = client.post(f"/collections/{uuid4()}/documents", json=_body())

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.json()["code"] == "collection_not_found"

    def test_the_same_content_twice_is_a_conflict(self, client: TestClient) -> None:
        collection_id = _a_collection(client)
        client.post(f"/collections/{collection_id}/documents", json=_body())

        response = client.post(f"/collections/{collection_id}/documents", json=_body())

        assert response.status_code == HTTPStatus.CONFLICT
        assert response.json()["code"] == "duplicate_document"

    def test_a_document_over_the_limit_is_too_large(self) -> None:
        service = Service(policy=IngestionPolicy(IngestionLimits(8, 10)))
        with TestClient(_app_for(service)) as client:
            collection_id = _a_collection(client)

            response = client.post(
                f"/collections/{collection_id}/documents",
                json=_body(content=b"nine byte"),
            )

        assert response.status_code == HTTPStatus.REQUEST_ENTITY_TOO_LARGE
        assert response.json()["code"] == "document_too_large"

    def test_a_full_collection_is_a_conflict(self) -> None:
        service = Service(policy=IngestionPolicy(IngestionLimits(1024, 1)))
        with TestClient(_app_for(service)) as client:
            collection_id = _a_collection(client)
            client.post(f"/collections/{collection_id}/documents", json=_body())

            response = client.post(
                f"/collections/{collection_id}/documents",
                json=_body(content=b"a different document"),
            )

        assert response.status_code == HTTPStatus.CONFLICT
        assert response.json()["code"] == "collection_full"

    def test_an_unusable_source_url_is_unprocessable(self, client: TestClient) -> None:
        collection_id = _a_collection(client)

        response = client.post(
            f"/collections/{collection_id}/documents",
            json=_body(source_url="not-a-url"),
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY
        assert response.json()["code"] == "invalid_source_url"

    def test_an_unknown_doc_type_is_refused_by_the_schema(
        self, client: TestClient
    ) -> None:
        collection_id = _a_collection(client)

        response = client.post(
            f"/collections/{collection_id}/documents",
            json=_body(doc_type="interpretive_dance"),
        )

        # Pydantic's own refusal, so the body is FastAPI's shape rather than
        # ours — the enum never reaches `DocType`, which would have raised
        # `ValueError` and become a 500.
        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_a_malformed_collection_id_never_reaches_the_domain(
        self, client: TestClient
    ) -> None:
        response = client.post("/collections/not-a-uuid/documents", json=_body())

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY

    def test_content_that_is_not_base64_is_refused(self, client: TestClient) -> None:
        collection_id = _a_collection(client)

        response = client.post(
            f"/collections/{collection_id}/documents",
            json={
                "content": "not base64!!",
                "metadata": {"source_library": "fastapi", "doc_type": "tutorial"},
            },
        )

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


class TestReportingOnADocument:
    def test_a_submitted_document_can_be_asked_about(self, client: TestClient) -> None:
        collection_id = _a_collection(client)
        document_id = client.post(
            f"/collections/{collection_id}/documents", json=_body()
        ).json()["document_id"]

        response = client.get(f"/documents/{document_id}")

        assert response.status_code == HTTPStatus.OK
        assert response.json() == {
            "document_id": document_id,
            "collection_id": collection_id,
            "status": "pending",
            "ingested_at": INGESTED_AT.isoformat().replace("+00:00", "Z"),
        }

    def test_an_unknown_document_is_not_found(self, client: TestClient) -> None:
        response = client.get(f"/documents/{uuid4()}")

        assert response.status_code == HTTPStatus.NOT_FOUND

    def test_a_malformed_document_id_is_unprocessable(self, client: TestClient) -> None:
        response = client.get("/documents/not-a-uuid")

        assert response.status_code == HTTPStatus.UNPROCESSABLE_ENTITY


class TestTheLayerItself:
    def test_the_endpoints_are_documented_automatically(
        self, client: TestClient
    ) -> None:
        """4.4's acceptance criterion: "Endpoints documented automatically"."""
        schema = client.get("/openapi.json").json()

        assert set(schema["paths"]) == {
            "/collections",
            "/collections/{collection_id}/documents",
            "/documents/{document_id}",
        }
        # The refusal shape is documented too, not just the happy path.
        assert "ErrorResponse" in schema["components"]["schemas"]

    def test_every_endpoint_is_synchronous(self) -> None:
        """ADR 0007 is a rule, so something other than review should hold it.

        `async def` is FastAPI's reflex and every port, use case and adapter in
        this service is synchronous. A future endpoint declared `async def`
        fails here rather than in a code review somebody skimmed.
        """
        from rag_ingestion.api.routes import router

        endpoints = [route.endpoint for route in router.routes]  # type: ignore[attr-defined]

        assert endpoints
        assert not [
            endpoint for endpoint in endpoints if inspect.iscoroutinefunction(endpoint)
        ]

    def test_the_application_ships_unwired(self) -> None:
        """4.4 deliberately satisfies no dependency; 4.5 does that.

        Without an override the provider raises, which is how this layer refuses
        to guess at its own infrastructure.
        """
        with (
            TestClient(create_app()) as unwired,
            pytest.raises(NotImplementedError, match="composition root"),
        ):
            unwired.post("/collections", json={"name": "nowhere"})
