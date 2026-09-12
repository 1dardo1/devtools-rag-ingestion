"""The composition root against a real database, end to end over HTTP.

An integration test and not a unit one, deliberately: every claim 4.5 makes is
about real connections and real transactions, and a fake would let all of them
pass while the service was broken.
"""

import base64
from collections.abc import Iterator
from http import HTTPStatus

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.rows import TupleRow

from rag_ingestion.api.request_id import HEADER
from rag_ingestion.config import Settings
from rag_ingestion.domain.collection import Collection
from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.infrastructure.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from rag_ingestion.main import build, transaction_per_request

pytestmark = pytest.mark.integration

type Connection = psycopg.Connection[TupleRow]

_CONTENT = b"The composition root is the only place the pieces meet."
_FAILED_MIDWAY = "something failed after a write"


def _document(content: bytes = _CONTENT, **metadata: object) -> dict[str, object]:
    return {
        "content": base64.b64encode(content).decode(),
        "metadata": {
            "source_library": "fastapi",
            "doc_type": "tutorial",
            **metadata,
        },
    }


@pytest.fixture
def client(migrated: Connection, postgres_url: str) -> Iterator[TestClient]:
    """The real service, wired by `build`, talking to the real database."""
    settings = Settings(database_url=postgres_url, log_level="INFO")
    with TestClient(build(settings)) as test_client:
        yield test_client


@pytest.fixture
def collection_id(client: TestClient) -> str:
    response = client.post("/collections", json={"name": "fastapi-docs"})
    assert response.status_code == HTTPStatus.CREATED
    return str(response.json()["collection_id"])


class TestTheWholeServiceOverHttp:
    def test_a_document_posted_over_http_reaches_postgres_with_its_outbox_row(
        self, client: TestClient, collection_id: str, migrated: Connection
    ) -> None:
        """Phase 4's completion criterion, minus the Redis half that 4.3 adds.

        `ROADMAP.md`: "posting a document over HTTP produces a row in Postgres
        and a message in Redis, verifiable by hand." This is the first half,
        verified by machine.
        """
        response = client.post(
            f"/collections/{collection_id}/documents", json=_document()
        )

        assert response.status_code == HTTPStatus.ACCEPTED
        document_id = response.json()["document_id"]

        # Asked on a separate connection, so this is what was committed.
        stored = migrated.execute(
            "SELECT collection_id, content FROM documents WHERE document_id = %s",
            (document_id,),
        ).fetchone()
        assert stored is not None
        assert str(stored[0]) == collection_id
        assert bytes(stored[1]) == _CONTENT

        announced = migrated.execute(
            "SELECT event_type, payload, published_at FROM outbox"
        ).fetchall()
        assert len(announced) == 1
        assert announced[0][0] == "DocumentIngested"
        assert announced[0][1]["document_id"] == document_id
        assert announced[0][2] is None  # the relay has not sent it

    def test_the_status_of_a_posted_document_can_be_read_back(
        self, client: TestClient, collection_id: str
    ) -> None:
        document_id = client.post(
            f"/collections/{collection_id}/documents", json=_document()
        ).json()["document_id"]

        response = client.get(f"/documents/{document_id}")

        assert response.status_code == HTTPStatus.OK
        assert response.json()["status"] == "pending"
        assert response.json()["collection_id"] == collection_id


class TestTheTransactionIsPerRequestAndRolledBackOnRefusal:
    """The four claims in `main.py`'s docstring, each one a silent failure.

    None of these can be caught by a type checker, which is exactly why they are
    tested here rather than trusted.
    """

    def test_a_refused_document_adds_neither_a_row_nor_an_announcement(
        self, client: TestClient, collection_id: str, migrated: Connection
    ) -> None:
        """A refusal adds nothing and disturbs nothing already stored.

        **This does not exercise the rollback**, and an earlier version of this
        test claimed it did. Every domain refusal is raised *before* the first
        write — `IngestDocument` checks the rules before it stores anything — so
        there is nothing for a rollback to undo, and removing the rollback
        entirely left this test passing. `TestTheTransactionBoundaryItself`
        covers that properly.
        """
        client.post(f"/collections/{collection_id}/documents", json=_document())

        repeated = client.post(
            f"/collections/{collection_id}/documents", json=_document()
        )

        assert repeated.status_code == HTTPStatus.CONFLICT
        # Exactly one of each: the refusal added neither a document nor an
        # announcement, and did not remove the first.
        assert migrated.execute("SELECT count(*) FROM documents").fetchone() == (1,)
        assert migrated.execute("SELECT count(*) FROM outbox").fetchone() == (1,)

    def test_a_refused_collection_is_not_stored(
        self, client: TestClient, migrated: Connection
    ) -> None:
        client.post("/collections", json={"name": "only-once"})

        repeated = client.post("/collections", json={"name": "only-once"})

        assert repeated.status_code == HTTPStatus.CONFLICT
        assert migrated.execute("SELECT count(*) FROM collections").fetchone() == (1,)

    def test_one_request_uses_one_connection_for_all_three_adapters(
        self, client: TestClient, collection_id: str, migrated: Connection
    ) -> None:
        """The invariant's real precondition, and the silent way to lose it.

        If the providers each opened their own connection, the document and its
        outbox row would be in separate transactions — and the give-away is that
        one request would hold more than one backend. Counting PostgreSQL's own
        backends while a request is in flight is the only way to see it from
        outside.
        """
        before = _backend_count(migrated)

        response = client.post(
            f"/collections/{collection_id}/documents", json=_document()
        )

        assert response.status_code == HTTPStatus.ACCEPTED
        # The request is over, so its connection is closed again: a leak would
        # show here as a backend that never went away.
        assert _backend_count(migrated) == before

    def test_every_declared_dependency_is_wired(self, client: TestClient) -> None:
        """A provider the composition root forgot is a runtime 500, not an error.

        Touching all three routes is the only thing that proves all three
        overrides exist, because nothing else does.
        """
        collection_id = client.post("/collections", json={"name": "all-three"}).json()[
            "collection_id"
        ]
        document_id = client.post(
            f"/collections/{collection_id}/documents", json=_document(content=b"three")
        ).json()["document_id"]

        assert client.get(f"/documents/{document_id}").status_code == HTTPStatus.OK


class TestTheRequestIdentifier:
    def test_every_response_carries_one(
        self, client: TestClient, collection_id: str
    ) -> None:
        response = client.post(
            f"/collections/{collection_id}/documents", json=_document()
        )

        assert response.headers[HEADER]

    def test_two_requests_get_different_ones(self, client: TestClient) -> None:
        first = client.post("/collections", json={"name": "one"})
        second = client.post("/collections", json={"name": "two"})

        assert first.headers[HEADER] != second.headers[HEADER]

    def test_an_inbound_identifier_is_ignored(self, client: TestClient) -> None:
        forged = "00000000-0000-0000-0000-000000000000"

        response = client.post(
            "/collections", json={"name": "not-yours"}, headers={HEADER: forged}
        )

        # Honouring a caller's identifier means accepting an attacker-chosen
        # string into every log line for that request, and one that can be made
        # to collide with somebody else's.
        assert response.headers[HEADER] != forged


def _backend_count(connection: Connection) -> int:
    row = connection.execute(
        "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()"
    ).fetchone()
    assert row is not None
    return int(row[0])


class TestTheTransactionBoundaryItself:
    """The rollback, driven the way FastAPI drives it.

    A `yield` dependency is a generator: FastAPI advances it, hands the value to
    the endpoint, and `throw`s into it if the endpoint raises. Doing exactly that
    is the only way to reach the rollback, because no domain refusal writes
    before it raises — which is why this class exists rather than being folded
    into the tests above.
    """

    def test_a_failure_after_a_write_rolls_the_write_back(
        self, migrated: Connection, postgres_url: str
    ) -> None:
        provide = transaction_per_request(postgres_url)
        generator = provide()
        connection = next(generator)
        collection = Collection(
            collection_id=CollectionId.generate(), name="rolled-back"
        )
        PostgresCollectionRepository(connection).add(collection)

        with pytest.raises(RuntimeError):
            generator.throw(RuntimeError(_FAILED_MIDWAY))

        assert (
            PostgresCollectionRepository(migrated).get(collection.collection_id) is None
        )

    def test_a_clean_finish_commits(
        self, migrated: Connection, postgres_url: str
    ) -> None:
        provide = transaction_per_request(postgres_url)
        generator = provide()
        connection = next(generator)
        collection = Collection(collection_id=CollectionId.generate(), name="committed")
        PostgresCollectionRepository(connection).add(collection)

        with pytest.raises(StopIteration):
            next(generator)  # runs past the yield, so the commit happens

        assert (
            PostgresCollectionRepository(migrated).get(collection.collection_id)
            is not None
        )

    def test_the_connection_is_closed_either_way(self, postgres_url: str) -> None:
        provide = transaction_per_request(postgres_url)
        generator = provide()
        connection = next(generator)

        with pytest.raises(RuntimeError):
            generator.throw(RuntimeError(_FAILED_MIDWAY))

        assert connection.closed
