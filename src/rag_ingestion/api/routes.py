"""The endpoints: the front door, and nothing more than a front door.

Each one translates a request into a command, hands it to a use case, and
translates the answer back. **No rule is enforced here** — not a size limit, not
a duplicate check, not a name's uniqueness. Every one of those lives in the
domain, and an endpoint that re-checked any of them would be a second place the
rule lives.

**Every handler is `def`, not `async def`.** FastAPI is async-native, so the
reflex is the other one; ADR 0007 examined and rejected it, because every port,
use case and adapter in this service is synchronous. FastAPI runs a `def`
endpoint in a threadpool, which is the correct way to call blocking code from an
async server — the defect would be `async def` plus `asyncio.run()` inside the
request, which looks modern and blocks the event loop.
"""

from http import HTTPStatus
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from rag_ingestion.api.dependencies import (
    create_collection,
    get_ingestion_status,
    ingest_document,
)
from rag_ingestion.api.schemas import (
    CollectionCreatedResponse,
    CreateCollectionRequest,
    DocumentAcceptedResponse,
    ErrorResponse,
    IngestDocumentRequest,
    IngestionStatusResponse,
)
from rag_ingestion.application.create_collection import (
    CreateCollection,
    CreateCollectionCommand,
)
from rag_ingestion.application.get_ingestion_status import GetIngestionStatus
from rag_ingestion.application.ingest_document import (
    IngestDocument,
    IngestDocumentCommand,
)
from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.document_id import DocumentId

router = APIRouter()

_REFUSAL = {"model": ErrorResponse}


@router.post(
    "/collections",
    status_code=HTTPStatus.CREATED,
    summary="Create a collection",
    responses={
        HTTPStatus.CONFLICT: _REFUSAL,
        HTTPStatus.UNPROCESSABLE_ENTITY: _REFUSAL,
    },
)
def post_collection(
    request: CreateCollectionRequest,
    collections: Annotated[CreateCollection, Depends(create_collection)],
) -> CollectionCreatedResponse:
    """Create a collection and return its identity.

    `201`, because the collection exists and is complete the moment this
    returns — unlike a document, which is only recorded.
    """
    collection_id = collections.execute(CreateCollectionCommand(name=request.name))
    return CollectionCreatedResponse(collection_id=collection_id.value)


@router.post(
    "/collections/{collection_id}/documents",
    status_code=HTTPStatus.ACCEPTED,
    summary="Submit a document for ingestion",
    responses={
        HTTPStatus.NOT_FOUND: _REFUSAL,
        HTTPStatus.CONFLICT: _REFUSAL,
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE: _REFUSAL,
        HTTPStatus.UNPROCESSABLE_ENTITY: _REFUSAL,
    },
)
def post_document(
    collection_id: UUID,
    request: IngestDocumentRequest,
    documents: Annotated[IngestDocument, Depends(ingest_document)],
) -> DocumentAcceptedResponse:
    """Accept a document and return its identity.

    **`202`, not `201`.** The document is recorded and nothing more: its status
    is `pending`, and whether it is ever indexed is the retrieval service's
    business. `201 Created` would claim a finished resource, and a client would
    be right to read it as "ready". The whole point of the outbox is that this
    service promises only to have written it down and told somebody.

    `collection_id` is typed `UUID`, so FastAPI refuses a malformed one with a
    `422` before any domain code runs. `CollectionId` then wraps a value that is
    already known to be a UUID, which is why `InvalidCollectionIdError` cannot
    reach the caller from here.
    """
    document_id = documents.execute(
        IngestDocumentCommand(
            collection_id=CollectionId(collection_id),
            content=request.content,
            metadata=request.metadata.to_domain(),
        )
    )
    return DocumentAcceptedResponse(document_id=document_id.value)


@router.get(
    "/documents/{document_id}",
    summary="Report on a submitted document",
    responses={HTTPStatus.NOT_FOUND: _REFUSAL},
)
def get_document(
    document_id: UUID,
    documents: Annotated[GetIngestionStatus, Depends(get_ingestion_status)],
) -> IngestionStatusResponse:
    """Describe a document, or refuse with `404` when there is no such document.

    The use case returns `None` rather than raising, because asking after a
    document that does not exist is an ordinary empty result. Turning that
    emptiness into a `404` is this layer's job and is stated as such in
    `GetIngestionStatus`: a status code is not a domain concern.
    """
    status = documents.execute(DocumentId(document_id))
    if status is None:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND,
            detail=f"There is no document {document_id}",
        )
    return IngestionStatusResponse.of(status)
