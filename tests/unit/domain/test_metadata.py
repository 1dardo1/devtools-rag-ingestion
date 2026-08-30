"""Metadata that could not be acted on later cannot be constructed now."""

import pytest

from rag_ingestion.domain.doc_type import DocType
from rag_ingestion.domain.errors import (
    DomainError,
    InvalidSourceUrlError,
    MissingMetadataFieldError,
)
from rag_ingestion.domain.metadata import Metadata


def test_the_two_required_fields_are_enough() -> None:
    metadata = Metadata(source_library="fastapi", doc_type=DocType.API_REFERENCE)

    assert metadata.library_version is None
    assert metadata.source_url is None


def test_every_field_can_be_supplied() -> None:
    metadata = Metadata(
        source_library="pydantic",
        doc_type=DocType.MIGRATION_GUIDE,
        library_version="2.13.4",
        source_url="https://docs.pydantic.dev/latest/migration/",
    )

    assert metadata.library_version == "2.13.4"
    assert metadata.source_url == "https://docs.pydantic.dev/latest/migration/"


def test_metadata_cannot_be_mutated() -> None:
    metadata = Metadata(source_library="qdrant", doc_type=DocType.OVERVIEW)

    with pytest.raises(AttributeError):
        # Deliberately breaking the frozen contract: the assignment is the
        # behaviour under test, so mypy is right to object and is silenced here.
        metadata.source_library = "redis"  # type: ignore[misc]


@pytest.mark.parametrize(
    "source_library",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="spaces only"),
        pytest.param("\t\n", id="whitespace only"),
    ],
)
def test_a_document_must_say_which_library_it_documents(source_library: str) -> None:
    with pytest.raises(MissingMetadataFieldError, match="source_library"):
        Metadata(source_library=source_library, doc_type=DocType.REFERENCE)


def test_a_present_version_must_not_be_blank() -> None:
    """Absent is said with `None`; a blank string is a mistake, not an absence."""
    with pytest.raises(MissingMetadataFieldError, match="library_version"):
        Metadata(
            source_library="uv",
            doc_type=DocType.CHANGELOG,
            library_version="   ",
        )


@pytest.mark.parametrize(
    "source_url",
    [
        pytest.param("", id="empty"),
        pytest.param("   ", id="whitespace only"),
        pytest.param("docs.pytest.org/en/stable/", id="no scheme"),
        pytest.param("/en/stable/fixtures.html", id="path only"),
        pytest.param("ftp://docs.pytest.org/", id="unsupported scheme"),
        pytest.param("file:///etc/passwd", id="local file"),
        pytest.param("javascript:alert(1)", id="script scheme"),
        pytest.param("https://", id="scheme without a host"),
    ],
)
def test_a_source_url_that_cannot_be_followed_is_rejected(source_url: str) -> None:
    with pytest.raises(InvalidSourceUrlError):
        Metadata(
            source_library="pytest",
            doc_type=DocType.HOW_TO,
            source_url=source_url,
        )


@pytest.mark.parametrize(
    "source_url",
    [
        pytest.param("http://example.test/page", id="http"),
        pytest.param("https://example.test/page", id="https"),
        pytest.param("https://example.test", id="no path"),
        pytest.param(
            "https://example.test:8443/page?x=1#frag", id="port, query, fragment"
        ),
    ],
)
def test_an_absolute_web_address_is_accepted(source_url: str) -> None:
    metadata = Metadata(
        source_library="pytest",
        doc_type=DocType.HOW_TO,
        source_url=source_url,
    )

    assert metadata.source_url == source_url


def test_surrounding_whitespace_is_stripped() -> None:
    metadata = Metadata(
        source_library="  fastapi  ",
        doc_type=DocType.TUTORIAL,
        library_version="  0.141.1  ",
        source_url="  https://fastapi.tiangolo.com/  ",
    )

    assert metadata.source_library == "fastapi"
    assert metadata.library_version == "0.141.1"
    assert metadata.source_url == "https://fastapi.tiangolo.com/"


def test_labels_a_human_would_call_identical_compare_equal() -> None:
    padded = Metadata(source_library=" redis ", doc_type=DocType.REFERENCE)
    plain = Metadata(source_library="redis", doc_type=DocType.REFERENCE)

    assert padded == plain


def test_rejections_are_domain_errors() -> None:
    with pytest.raises(DomainError):
        Metadata(source_library="", doc_type=DocType.OTHER)


def test_doc_type_values_are_stable_readable_strings() -> None:
    assert DocType.API_REFERENCE.value == "api_reference"
    assert str(DocType.MIGRATION_GUIDE) == "migration_guide"


def test_every_doc_type_has_a_distinct_value() -> None:
    values = [member.value for member in DocType]

    assert len(values) == len(set(values))
