"""Where the endpoints get their use cases, and why it is not here.

`docs/BUILD-PLAN.md` keeps the web layer and the storage chain apart until 4.5:
"the web layer talks only to the use cases; the storage chain only to the
database. They meet for the first time at 4.5." These functions are that seam.
Each one declares the *shape* of a dependency and refuses to supply it; the
composition root overrides them with the real thing, and a test overrides them
with fakes.

**Why `Depends` rather than building the routers with their use cases passed
in.** A factory taking an `IngestDocument` would be more explicit and is the
pattern the rest of this codebase uses — but it would hold **one** use case for
the lifetime of the process, and therefore one connection and one transaction
for the lifetime of the process. The transaction has to be per request. That is
the whole argument, and ADR 0015 records it.
"""

from rag_ingestion.application.create_collection import CreateCollection
from rag_ingestion.application.get_ingestion_status import GetIngestionStatus
from rag_ingestion.application.ingest_document import IngestDocument

_NOT_WIRED = (
    "No {name} was provided. This dependency is deliberately unimplemented in"
    " 4.4: the composition root overrides it, and a test overrides it with"
    " fakes. See ADR 0015."
)


def ingest_document() -> IngestDocument:
    """Supply the use case that accepts a document. Overridden at composition."""
    message = _NOT_WIRED.format(name="IngestDocument")
    raise NotImplementedError(message)


def create_collection() -> CreateCollection:
    """Supply the use case that creates a collection. Overridden at composition."""
    message = _NOT_WIRED.format(name="CreateCollection")
    raise NotImplementedError(message)


def get_ingestion_status() -> GetIngestionStatus:
    """Supply the use case that reports on a document. Overridden at composition."""
    message = _NOT_WIRED.format(name="GetIngestionStatus")
    raise NotImplementedError(message)
