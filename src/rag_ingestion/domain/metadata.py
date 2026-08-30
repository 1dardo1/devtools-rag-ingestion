"""What a document says about itself: which library, which version, what kind."""

from dataclasses import dataclass
from urllib.parse import urlparse

from rag_ingestion.domain.doc_type import DocType
from rag_ingestion.domain.errors import (
    InvalidSourceUrlError,
    MissingMetadataFieldError,
)

_ALLOWED_URL_SCHEMES = frozenset({"http", "https"})


def _stripped_or_rejected(value: str, field_name: str) -> str:
    stripped = value.strip()
    if not stripped:
        raise MissingMetadataFieldError(field_name)
    return stripped


def _reject_unusable_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme not in _ALLOWED_URL_SCHEMES or not parsed.netloc:
        raise InvalidSourceUrlError(value)


@dataclass(frozen=True, slots=True)
class Metadata:
    """The labels carried alongside a document.

    These four fields are the only part of this service the corpus affects.
    Everything else — entities, rules, the outbox, every port — would be
    identical for any other body of documents.

    `source_library` and `doc_type` are required: a document nobody can say
    which library it belongs to, or what kind of page it is, cannot be
    retrieved usefully. `library_version` and `source_url` are optional,
    because unversioned documentation exists and a document may arrive by hand
    with no address to point back to. An optional field that is present must
    still be usable, so a blank string is rejected rather than quietly treated
    as absent — passing nothing is how you say "there isn't one".

    Surrounding whitespace is stripped on construction, so that two labels a
    human would call identical compare equal.
    """

    source_library: str
    doc_type: DocType
    library_version: str | None = None
    source_url: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_library",
            _stripped_or_rejected(self.source_library, "source_library"),
        )

        library_version = self.library_version
        if library_version is not None:
            object.__setattr__(
                self,
                "library_version",
                _stripped_or_rejected(library_version, "library_version"),
            )

        source_url = self.source_url
        if source_url is not None:
            source_url = source_url.strip()
            _reject_unusable_url(source_url)
            object.__setattr__(self, "source_url", source_url)
