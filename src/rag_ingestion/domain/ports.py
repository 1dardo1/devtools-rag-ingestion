"""The sockets the outside world plugs into.

Shapes only: no database, no broker, no HTTP. Each is a `typing.Protocol`, so
an adapter satisfies one by having the right methods rather than by inheriting
from it — principle 4.3. Nothing here imports an implementation, and no
implementation is required to import this module.

**These are synchronous**, and ADR 0007 records why: nothing here makes a slow
call to a third party, so the saving async offers is real but small, while its
cost — every caller coloured, an async test plugin in the toolchain — is paid
everywhere. That record also names the risk, which is a change of workload
rather than of volume.
"""

from datetime import datetime
from typing import Protocol

from rag_ingestion.domain.collection import Collection
from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.events import DocumentIngested


class Clock(Protocol):
    """Where "now" comes from.

    Reading a clock is I/O wearing a disguise: the answer comes from outside
    the process and differs on every call. Left unguarded it becomes a hidden
    dependency on real time, and any test that asserts on a timestamp either
    turns non-deterministic or resorts to patching `datetime` — which couples
    the test to the implementation it is supposed to be independent of.

    So it goes behind a port for the same reason the database does. Production
    supplies a clock that reads the system time; a test supplies one that
    returns a fixed instant, and the assertion becomes an equality.

    Not named in `ROADMAP.md` 1.5, which lists only `DocumentRepository` and
    `EventPublisher`. **ADR 0009 records why it exists anyway**, along with the
    alternatives rejected and the rule that follows from it: the clock is read
    once per ingestion, and that one instant reaches both the document and the
    event.
    """

    def now(self) -> datetime:
        """Return the current instant, with a timezone attached."""
        ...


class DocumentRepository(Protocol):
    """Where documents are kept.

    The two query methods exist because the ingestion rules need answers, not
    data: `IngestionPolicy` asks whether content is already present and whether
    a collection has room, and it takes the answer rather than the haystack.
    Putting those questions here means the database can answer them with an
    index instead of the application loading rows to count them.
    """

    def add(self, document: Document, content: bytes) -> None:
        """Store a document that has passed every rule, with its content.

        The bytes travel as an argument because `Document` deliberately does
        not hold them, and they are written in the same call as the record so
        that an adapter binds both to one transaction without being asked to.
        A record whose content was never stored is the same class of failure
        the outbox exists to prevent, one table over.
        """
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

    def exists_with_name(self, name: str) -> bool:
        """Answer whether a collection already goes by this name.

        A question, not a haystack — the same shape as
        `DocumentRepository.exists_with_content_hash`, and for the same reason:
        the database answers it with an index instead of the application
        loading every collection to look.

        The name arrives already stripped, because `Collection` normalises it
        on construction and the use case asks with the normalised value.

        **This is the legibility half of the rule, not the guarantee.** Between
        this answer and the write there is a window in which another process
        can insert the same name. Phase 4 closes it with a unique index; this
        exists so the caller gets a domain error explaining the refusal rather
        than a driver's integrity error.
        """
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
