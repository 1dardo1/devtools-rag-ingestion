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
