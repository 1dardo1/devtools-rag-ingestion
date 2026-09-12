"""Turning a domain refusal into an HTTP status code.

A status code is not a domain concern — `GetIngestionStatus` says so in its own
docstring — so the mapping lives here and nowhere else. One table, registered as
exception handlers, rather than `try`/`except` in each endpoint: the same refusal
can come from more than one route, and a mapping repeated per route is a mapping
that drifts.

This is **not** the logging and error-reporting decision that
`docs/BUILD-PLAN.md` still has open before 4.5. That one is about what the
service records when something goes wrong unattended. This is only about what it
says to the caller in front of it.
"""

from http import HTTPStatus

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from rag_ingestion.api.schemas import ErrorResponse
from rag_ingestion.domain.errors import (
    CollectionFullError,
    CollectionNotFoundError,
    DocumentTooLargeError,
    DomainError,
    DuplicateCollectionNameError,
    DuplicateDocumentError,
    InvalidSourceUrlError,
    MissingCollectionNameError,
    MissingMetadataFieldError,
)

# The table *is* the contract. Each entry pairs a status with a stable string a
# client can branch on, which matters because three different refusals are all
# `409`: a status code alone cannot tell a duplicate name from a duplicate
# document from a collection that is full.
#
# The codes are written out rather than derived from the class names. A class
# rename is a refactor; these strings are on the wire, where a rename is a
# breaking change — the same reasoning ADR 0014 applied to the event type.
_REFUSALS: dict[type[DomainError], tuple[HTTPStatus, str]] = {
    CollectionNotFoundError: (HTTPStatus.NOT_FOUND, "collection_not_found"),
    DuplicateCollectionNameError: (HTTPStatus.CONFLICT, "duplicate_collection_name"),
    DuplicateDocumentError: (HTTPStatus.CONFLICT, "duplicate_document"),
    CollectionFullError: (HTTPStatus.CONFLICT, "collection_full"),
    DocumentTooLargeError: (
        HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
        "document_too_large",
    ),
    # Raised while a request is being turned into domain objects, so they are
    # malformed input rather than a conflict with stored state. 422 is what
    # FastAPI already returns for a request it cannot parse, which keeps one
    # meaning for one status.
    MissingMetadataFieldError: (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        "missing_metadata_field",
    ),
    InvalidSourceUrlError: (HTTPStatus.UNPROCESSABLE_ENTITY, "invalid_source_url"),
    MissingCollectionNameError: (
        HTTPStatus.UNPROCESSABLE_ENTITY,
        "missing_collection_name",
    ),
}

_UNMAPPED = (HTTPStatus.INTERNAL_SERVER_ERROR, "internal_error")


def register(app: FastAPI) -> None:
    """Teach an application how to answer every domain refusal."""
    app.add_exception_handler(DomainError, _handle_domain_error)


def _handle_domain_error(
    request: Request,  # noqa: ARG001 - Starlette's handler signature requires it
    exc: Exception,
) -> JSONResponse:
    """Answer a domain refusal with its mapped status and a stable code.

    Registered against `DomainError`, so a *new* domain error is answered
    without anybody remembering to come back here — as a `500`, which is the
    honest answer: an error this file has never been told about is a gap in this
    table, not a request the caller got wrong. Defaulting to `400` would blame
    the caller for our omission and hide the gap behind a plausible answer.

    The parameter is typed `Exception` because that is Starlette's handler
    signature, not because anything but a `DomainError` can arrive here. The
    `isinstance` narrowing is what keeps the table's own type honest rather than
    asserting the invariant with a `cast`.
    """
    status, code = _UNMAPPED
    if isinstance(exc, DomainError):
        status, code = _REFUSALS.get(type(exc), _UNMAPPED)
    body = ErrorResponse(code=code, detail=str(exc))
    return JSONResponse(status_code=status, content=body.model_dump())
