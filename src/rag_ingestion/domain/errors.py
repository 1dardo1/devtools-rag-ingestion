"""Errors the domain raises when an invariant would be broken.

Each error builds its own message, so a call site reads as
`raise MissingMetadataFieldError("source_library")` rather than carrying an
ad-hoc string. That is the shape ADR 0006's `TRY003` and `EM` rules push
towards, and it keeps the wording of an error in one place rather than spread
across every site that raises it.
"""


class DomainError(Exception):
    """Base class for every error raised by the domain layer.

    Callers that want to distinguish "the request was invalid" from "something
    broke" can catch this one class rather than enumerate subclasses.
    """


class InvalidDocumentIdError(DomainError):
    """Raised when a string cannot be read as a document identifier."""

    def __init__(self, value: str) -> None:
        super().__init__(f"{value!r} is not a valid document identifier")


class InvalidContentHashError(DomainError):
    """Raised when a string is not a lowercase hexadecimal SHA-256 digest."""

    def __init__(self, value: str) -> None:
        super().__init__(f"{value!r} is not a valid SHA-256 digest")


class MissingMetadataFieldError(DomainError):
    """Raised when a metadata field is absent or blank where it is required."""

    def __init__(self, field_name: str) -> None:
        super().__init__(
            f"Metadata field {field_name!r} is required and must not be blank"
        )


class InvalidSourceUrlError(DomainError):
    """Raised when a source URL is not an absolute http or https address."""

    def __init__(self, value: str) -> None:
        super().__init__(f"{value!r} is not an absolute http or https URL")


class InvalidCollectionIdError(DomainError):
    """Raised when a string cannot be read as a collection identifier."""

    def __init__(self, value: str) -> None:
        super().__init__(f"{value!r} is not a valid collection identifier")


class NegativeDocumentSizeError(DomainError):
    """Raised when a document claims to occupy fewer than zero bytes."""

    def __init__(self, size_in_bytes: int) -> None:
        super().__init__(f"A document cannot be {size_in_bytes} bytes long")


class MissingCollectionNameError(DomainError):
    """Raised when a collection is created without a usable name."""

    def __init__(self) -> None:
        super().__init__("A collection must have a name that is not blank")


class IllegalStatusTransitionError(DomainError):
    """Raised when a document is asked to move to a status it cannot reach."""

    def __init__(self, current: str, requested: str) -> None:
        super().__init__(f"A document that is {current!r} cannot become {requested!r}")


class DocumentTooLargeError(DomainError):
    """Raised when a document exceeds the largest size the service accepts."""

    def __init__(self, size_in_bytes: int, limit_in_bytes: int) -> None:
        super().__init__(
            f"A document of {size_in_bytes} bytes exceeds the "
            f"{limit_in_bytes} byte limit"
        )


class CollectionFullError(DomainError):
    """Raised when a collection already holds as many documents as it may."""

    def __init__(self, document_count: int, limit: int) -> None:
        super().__init__(
            f"A collection already holding {document_count} documents cannot "
            f"take another; the limit is {limit}"
        )


class DuplicateDocumentError(DomainError):
    """Raised when a collection already holds this exact content."""

    def __init__(self, content_hash: str, collection_id: str) -> None:
        super().__init__(
            f"Collection {collection_id} already holds a document with "
            f"content hash {content_hash}"
        )


class InvalidLimitError(DomainError):
    """Raised when a configured limit would make ingestion impossible."""

    def __init__(self, limit_name: str, value: int) -> None:
        super().__init__(f"Limit {limit_name!r} must be positive, not {value}")
