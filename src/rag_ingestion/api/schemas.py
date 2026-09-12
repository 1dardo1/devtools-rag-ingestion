"""What the HTTP layer accepts and returns.

Pydantic models, separate from the domain's value objects on purpose. These
describe a wire format that may change for reasons that have nothing to do with
the domain — a field renamed for a client's convenience, a shape versioned — and
the domain should not move when it does. The translation runs in one direction
only, in `to_domain`, so nothing inward knows these exist.
"""

from datetime import datetime
from uuid import UUID

from pydantic import Base64Bytes, BaseModel, ConfigDict, Field

from rag_ingestion.application.get_ingestion_status import IngestionStatus
from rag_ingestion.domain.doc_type import DocType
from rag_ingestion.domain.document_status import DocumentStatus
from rag_ingestion.domain.metadata import Metadata


class MetadataRequest(BaseModel):
    """The labels a caller supplies alongside a document.

    `doc_type` is typed as the domain's `DocType`, so Pydantic rejects an
    unknown kind with a 422 that lists the allowed values, and the generated
    OpenAPI enumerates all of them. Accepting a plain string and calling
    `DocType(...)` would turn the same mistake into a 500 — the enum raises
    `ValueError`, which is not a `DomainError` and would not be mapped.
    """

    model_config = ConfigDict(extra="forbid")

    source_library: str
    doc_type: DocType
    library_version: str | None = None
    source_url: str | None = None

    def to_domain(self) -> Metadata:
        """Build the domain value object, letting it enforce its own rules.

        Deliberately not re-validated here. `Metadata` strips whitespace,
        rejects a blank required field and refuses a URL it cannot use; copying
        those rules into a Pydantic validator would put the same rule in two
        places, and the copy would be the one that drifts.
        """
        return Metadata(
            source_library=self.source_library,
            doc_type=self.doc_type,
            library_version=self.library_version,
            source_url=self.source_url,
        )


class IngestDocumentRequest(BaseModel):
    """A document being submitted.

    **The content is base64.** A document is bytes as far as this service is
    concerned, and base64 is the only one of the obvious options that carries
    arbitrary bytes through JSON without narrowing what may be submitted. ADR
    0015 records the two that were rejected.
    """

    model_config = ConfigDict(extra="forbid")

    content: Base64Bytes = Field(
        description="The document's bytes, base64-encoded.",
    )
    metadata: MetadataRequest


class CreateCollectionRequest(BaseModel):
    """A collection being created."""

    model_config = ConfigDict(extra="forbid")

    name: str


class CollectionCreatedResponse(BaseModel):
    """The identity of a collection that now exists."""

    collection_id: UUID


class DocumentAcceptedResponse(BaseModel):
    """The identity of a document the service has taken responsibility for."""

    document_id: UUID


class IngestionStatusResponse(BaseModel):
    """What happened to a document somebody submitted.

    Built from the `IngestionStatus` read model rather than from `Document`,
    which is the whole reason that read model exists: the entity carries three
    transition methods, and a response schema built from it would put them one
    attribute access from a request handler.
    """

    document_id: UUID
    collection_id: UUID
    status: DocumentStatus
    ingested_at: datetime

    @classmethod
    def of(cls, status: IngestionStatus) -> IngestionStatusResponse:
        """Describe a read model on the wire."""
        return cls(
            document_id=status.document_id.value,
            collection_id=status.collection_id.value,
            status=status.status,
            ingested_at=status.ingested_at,
        )


class ErrorResponse(BaseModel):
    """The shape every refusal takes.

    `code` is a stable machine-readable string and `detail` is the domain's own
    message. The `code` exists because several distinct refusals share a status:
    a duplicate name, a duplicate document and a full collection are all `409`,
    and a client that needs to tell them apart should not have to parse English.
    """

    code: str
    detail: str
