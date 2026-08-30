"""The rules a document must satisfy before a collection will take it."""

from dataclasses import dataclass, field

from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.errors import (
    CollectionFullError,
    DocumentTooLargeError,
    DuplicateDocumentError,
)
from rag_ingestion.domain.limits import IngestionLimits


@dataclass(frozen=True, slots=True)
class IngestionPolicy:
    """The three checks that stand between a submission and a stored document.

    Each is a question the policy answers, not a lookup it performs. The
    duplicate check in particular takes `already_present` as an answer rather
    than a collection of existing hashes: asking the caller to load ten
    thousand digests so the domain can scan them would move a database index
    into application memory. The use case in Phase 2 asks the repository, and
    brings the answer here.

    That split is what keeps these rules testable without infrastructure while
    still being the only place the decisions are made.
    """

    limits: IngestionLimits = field(default_factory=IngestionLimits)

    def ensure_document_fits(self, size_in_bytes: int) -> None:
        """Reject a document larger than the service accepts."""
        if size_in_bytes > self.limits.max_document_size_in_bytes:
            raise DocumentTooLargeError(
                size_in_bytes, self.limits.max_document_size_in_bytes
            )

    def ensure_collection_has_room(self, document_count: int) -> None:
        """Reject a document that would take a collection past its ceiling."""
        if document_count >= self.limits.max_documents_per_collection:
            raise CollectionFullError(
                document_count, self.limits.max_documents_per_collection
            )

    def ensure_content_is_new(
        self,
        content_hash: ContentHash,
        collection_id: CollectionId,
        *,
        already_present: bool,
    ) -> None:
        """Reject content the collection already holds.

        Deduplication is scoped to the collection, not to the service: the same
        page may legitimately appear in two collections, and treating that as a
        duplicate would make collections leak into each other.
        """
        if already_present:
            raise DuplicateDocumentError(str(content_hash), str(collection_id))
