"""The composition root: the one place the real pieces meet the sockets.

`ARCHITECTURE.md` asks for exactly one such place, so that swapping a database
or a message channel is editing one file rather than hunting through a codebase.
`docs/BUILD-PLAN.md` adds the other half: the web layer and the storage chain
have been kept apart since 4.1, and this is where they are introduced.

**Four things here are load-bearing, and no type checker can check any of
them.** They are collected in one docstring because a reader who changes this
file needs all four at once:

1. **All three adapters are built from one connection.** A publisher and a
   repository on two different connections typecheck perfectly and are not
   atomic, which would quietly destroy the invariant 4.2 exists to provide.
   ADR 0013, ADR 0014.
2. **That connection, and its commit, are per request.** Which is why the
   endpoints take their use cases through `Depends` rather than holding them —
   a use case built once at startup would hold one transaction forever. ADR
   0015.
3. **Every provider `api/dependencies.py` declares must be overridden here.**
   A forgotten one is a runtime `500`, not a compile error.
4. **`observability.configure` is called here**, because it is deliberately not
   called on import. ADR 0016.
"""

from collections.abc import Callable, Generator
from typing import Annotated

import psycopg
from fastapi import Depends, FastAPI
from psycopg.rows import TupleRow

from rag_ingestion import observability
from rag_ingestion.api import dependencies
from rag_ingestion.api.app import create_app
from rag_ingestion.api.request_id import RequestIdMiddleware
from rag_ingestion.application.create_collection import CreateCollection
from rag_ingestion.application.get_ingestion_status import GetIngestionStatus
from rag_ingestion.application.ingest_document import IngestDocument
from rag_ingestion.config import Settings
from rag_ingestion.infrastructure.postgres.collection_repository import (
    PostgresCollectionRepository,
)
from rag_ingestion.infrastructure.postgres.document_repository import (
    PostgresDocumentRepository,
)
from rag_ingestion.infrastructure.postgres.outbox_event_publisher import (
    PostgresOutboxEventPublisher,
)
from rag_ingestion.infrastructure.system_clock import SystemClock

type Connection = psycopg.Connection[TupleRow]


def transaction_per_request(
    database_url: str,
) -> Callable[[], Generator[Connection]]:
    """Build the provider that gives one request one connection and one commit.

    **Module-level and returning the provider, rather than a closure inside
    `build`.** The transaction boundary is the most consequential thing in this
    file, and a closure cannot be tested without standing up an application and
    finding a request that fails in the right place. This can be driven directly:
    a test advances the generator, writes through the connection, throws into it,
    and asks a second connection what survived.

    The commit is here and nowhere else — no adapter commits, per ADR 0013 — so
    this function is the entire transaction boundary of the service.

    A `yield` dependency sees an exception raised by the endpoint **even when an
    exception handler has already turned it into a response**; that was verified
    rather than assumed, because without it a request that failed after writing
    would commit.

    **The `rollback()` is redundant and kept deliberately.** `close()` in the
    `finally` already discards an open transaction — verified against a real
    server — so removing the `rollback()` changes nothing observable, and no test
    can distinguish the two. It stays because for the single most important
    invariant in this service a reader should see where the transaction ends
    without having to know that detail of the driver. It is documentation that
    cannot drift from the code, not behaviour.
    """

    # `Generator`, not `Iterator`: FastAPI *throws* into this on failure, and
    # `Iterator` does not promise a `throw`. The wider type would have hidden
    # that from the tests that rely on it.
    def provide() -> Generator[Connection]:
        connection = psycopg.connect(database_url)
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    return provide


def build(settings: Settings | None = None) -> FastAPI:
    """Wire the real service together and return it.

    Takes its settings as an argument so that a test can supply them rather than
    arrange an environment. `None` means read the environment, which is what a
    deployment does.
    """
    # `Settings()` with no arguments is a false positive, not a mistake:
    # `database_url` is required and `pydantic-settings` fills it from the
    # environment, which `mypy` cannot see. The narrowest possible silence.
    #
    # `plugins = ["pydantic.mypy"]` removes the warning and was rejected on
    # evidence: with the plugin on, `mypy` stops reporting a genuinely wrong
    # argument type to a model constructor, so it trades one false positive for
    # a lost true one. ADR 0017.
    resolved = settings if settings is not None else Settings()  # type: ignore[call-arg]
    observability.configure(level=resolved.log_level)

    unit_of_work = transaction_per_request(resolved.database_url)

    def ingest_document(
        connection: Annotated[Connection, Depends(unit_of_work)],
    ) -> IngestDocument:
        # All three adapters on the one connection. This is point 1 above, and
        # it is the only line in the file where getting it wrong is silent.
        return IngestDocument(
            documents=PostgresDocumentRepository(connection),
            collections=PostgresCollectionRepository(connection),
            events=PostgresOutboxEventPublisher(connection),
            clock=SystemClock(),
        )

    def create_collection(
        connection: Annotated[Connection, Depends(unit_of_work)],
    ) -> CreateCollection:
        return CreateCollection(collections=PostgresCollectionRepository(connection))

    def get_ingestion_status(
        connection: Annotated[Connection, Depends(unit_of_work)],
    ) -> GetIngestionStatus:
        return GetIngestionStatus(documents=PostgresDocumentRepository(connection))

    app = create_app()
    app.add_middleware(RequestIdMiddleware)
    app.dependency_overrides[dependencies.ingest_document] = ingest_document
    app.dependency_overrides[dependencies.create_collection] = create_collection
    app.dependency_overrides[dependencies.get_ingestion_status] = get_ingestion_status
    return app
