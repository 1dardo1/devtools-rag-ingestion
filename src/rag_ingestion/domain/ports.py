"""The sockets the outside world plugs into.

Shapes only: no database, no broker, no HTTP. Each is a `typing.Protocol`, so
an adapter satisfies one by having the right methods rather than by inheriting
from it — principle 4.3. Nothing here imports an implementation, and no
implementation is required to import this module.

**These are synchronous.** Nothing in the domain or the use cases performs I/O
of its own, so making them `async` would colour every caller for the benefit
of the adapters alone, and would pull an async test plugin into the toolchain.
FastAPI runs synchronous endpoints in a worker threadpool, which is a
well-trodden path for a service whose slow part is a database call. The cost
is real and worth naming: that threadpool has a bounded worker count, and if
this service ever became throughput-bound rather than correctness-bound, the
ports would have to change and every caller with them. Phase 2 is the last
cheap moment to revisit it.
"""

from typing import Protocol

from rag_ingestion.domain.collection import Collection
from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.events import DocumentIngested


class DocumentRepository(Protocol):
    """Where documents are kept.

    The two query methods exist because the ingestion rules need answers, not
    data: `IngestionPolicy` asks whether content is already present and whether
    a collection has room, and it takes the answer rather than the haystack.
    Putting those questions here means the database can answer them with an
    index instead of the application loading rows to count them.
    """

    def add(self, document: Document) -> None:
        """Store a document that has passed every rule."""
        ...

    def get(self, document_id: DocumentId) -> Document | None:
        """Retrieve a document, or `None` when there is no such document.

        `None` rather than an exception: a caller asking after a document it
        cannot find is an ordinary outcome for a status lookup, not an error.
        """
        ...

    def exists_with_content_hash(
        self, collection_id: CollectionId, content_hash: ContentHash
    ) -> bool:
        """Answer whether this collection already holds this exact content."""
        ...

    def count_in_collection(self, collection_id: CollectionId) -> int:
        """Count the documents a collection currently holds."""
        ...


class CollectionRepository(Protocol):
    """Where collections are kept.

    Not named in `ROADMAP.md` 1.5, which lists only `DocumentRepository` and
    `EventPublisher`. It is needed regardless: unit 2.2 creates collections,
    and folding that into `DocumentRepository` would give one port two
    responsibilities for no reason beyond matching a list.
    """

    def add(self, collection: Collection) -> None:
        """Store a newly created collection."""
        ...

    def get(self, collection_id: CollectionId) -> Collection | None:
        """Retrieve a collection, or `None` when there is no such collection."""
        ...


class EventPublisher(Protocol):
    """Where announcements go.

    **The single most important invariant in this service lives behind this
    port.** Its Phase 4 implementation does not talk to Redis. It writes a row
    to an outbox table *in the same database transaction as the document
    itself*, and a separate relay process publishes it afterwards. That is what
    makes it impossible to store a document nobody is ever told about, even if
    the broker is down or the process dies in between.

    The name says `publish` because that is what the use case means. How the
    transaction spanning `DocumentRepository.add` and this call is scoped is
    not decided here, and cannot be: it is a Phase 4 question, and it may well
    need a unit-of-work abstraction that does not exist yet. What matters at
    this stage is that nothing in this shape prevents one — the use case calls
    two collaborators, and an adapter is free to bind both to the same
    transaction at the composition root.
    """

    def publish(self, event: DocumentIngested) -> None:
        """Announce that a document has been ingested."""
        ...
