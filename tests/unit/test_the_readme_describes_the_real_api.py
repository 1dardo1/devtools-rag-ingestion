"""The sixth guard: the README's worked example describes the real API. ADR 0023.

`README.md` now shows the three requests a caller actually makes, because
`ROADMAP.md` 7.3 asks for "the explanation someone reads cold" and a reader who
cannot tell what the service accepts has not been told what it is.

**The risk that comes with that is rot, and it is not hypothetical.** Before this
change the README described `infrastructure/` as holding an "outbox relay" and a
"Redis publisher", neither of which has been written, and claimed CI ran "these
five commands" when CI has three jobs. Documentation drifts silently because
nothing executes it.

**What this does and does not check.** It does not parse the shell out of the
markdown and run it — that would need a bash grammar and a live server to be worth
anything. It checks the two things that actually drift: that every route and field
the README names still exists in the generated OpenAPI document, and that the
README still names them. The lists below are the contract between the two, and
both directions fail loudly.
"""

from pathlib import Path
from typing import Any

import pytest

from rag_ingestion.api.app import create_app

_README = Path(__file__).resolve().parents[2] / "README.md"

# Method, path, and the success status the README claims. The status is included
# because ADR 0015 made `202` rather than `201` a deliberate statement about what
# the service promises, and a README that said `201` would be undoing the
# decision in prose.
_DOCUMENTED_ROUTES: tuple[tuple[str, str, str], ...] = (
    ("post", "/collections", "201"),
    ("post", "/collections/{collection_id}/documents", "202"),
    ("get", "/documents/{document_id}", "200"),
)

# Schema name -> the field names the README shows. A rename in either direction
# breaks this, which is the point: these strings are on the wire and in the
# document a reader trusts.
_DOCUMENTED_FIELDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("CreateCollectionRequest", ("name",)),
    ("IngestDocumentRequest", ("content", "metadata")),
    (
        "MetadataRequest",
        ("source_library", "doc_type", "library_version", "source_url"),
    ),
    ("CollectionCreatedResponse", ("collection_id",)),
    ("DocumentAcceptedResponse", ("document_id",)),
    (
        "IngestionStatusResponse",
        ("document_id", "collection_id", "status", "ingested_at"),
    ),
    ("ErrorResponse", ("code", "detail")),
)

# Every `code` the README's refusal table lists. The table is the reason the field
# exists — ADR 0015 added it because three refusals share `409` — so a code that
# changed without the table changing would leave a client following instructions
# that do not work.
_DOCUMENTED_CODES: tuple[str, ...] = (
    "collection_not_found",
    "duplicate_collection_name",
    "duplicate_document",
    "collection_full",
    "document_too_large",
    "request_too_large",
    "missing_metadata_field",
    "invalid_source_url",
    "missing_collection_name",
)


@pytest.fixture(scope="module")
def schema() -> dict[str, Any]:
    """The OpenAPI document the service actually generates."""
    return create_app().openapi()


@pytest.fixture(scope="module")
def readme() -> str:
    return _README.read_text(encoding="utf-8")


class TestTheApiStillHasWhatTheReadmeShows:
    def test_every_documented_route_exists(self, schema: dict[str, Any]) -> None:
        for method, path, status in _DOCUMENTED_ROUTES:
            assert path in schema["paths"], (
                f"the README documents {method.upper()} {path}, which no longer exists"
            )
            operation = schema["paths"][path].get(method)
            assert operation is not None, (
                f"{path} exists but no longer accepts {method.upper()}"
            )
            assert status in operation["responses"], (
                f"the README says {method.upper()} {path} answers {status};"
                f" it now answers {sorted(operation['responses'])}"
            )

    def test_every_documented_field_exists(self, schema: dict[str, Any]) -> None:
        schemas = schema["components"]["schemas"]
        for name, fields in _DOCUMENTED_FIELDS:
            assert name in schemas, (
                f"the README shows the shape of {name}, which no longer exists"
            )
            properties = schemas[name]["properties"]
            missing = [field for field in fields if field not in properties]
            assert not missing, (
                f"{name} no longer has {missing}, which the README shows"
            )

    def test_every_documented_refusal_code_is_one_the_service_sends(self) -> None:
        """Read from the refusal table itself, not from a second list of strings."""
        from rag_ingestion.api import body_limit
        from rag_ingestion.api.error_handling import _REFUSALS

        real = {code for _, code in _REFUSALS.values()} | {body_limit.CODE}

        assert set(_DOCUMENTED_CODES) == real, (
            "the README's refusal table and the service disagree."
            f" Only in the README: {sorted(set(_DOCUMENTED_CODES) - real)}."
            f" Only in the service: {sorted(real - set(_DOCUMENTED_CODES))}."
        )


class TestTheReadmeStillShowsThem:
    """The other direction, which a one-way check would miss.

    Without this, deleting the whole "What it accepts" section would leave the
    tests above passing — they would be asserting that the API matches a list in a
    test file, which is not what the guard is for.
    """

    def test_every_documented_route_appears_in_the_readme(self, readme: str) -> None:
        for _, path, _ in _DOCUMENTED_ROUTES:
            # The README writes the path with a real value substituted for the
            # placeholder, so the literal template will not appear. Its fixed
            # leading segment will.
            fixed = path.split("{")[0].rstrip("/")
            assert fixed in readme, f"the README no longer mentions {fixed}"

    def test_every_documented_field_appears_in_the_readme(self, readme: str) -> None:
        for _, fields in _DOCUMENTED_FIELDS:
            for field in fields:
                assert field in readme, f"the README no longer mentions {field}"

    def test_every_documented_refusal_code_appears_in_the_readme(
        self, readme: str
    ) -> None:
        for code in _DOCUMENTED_CODES:
            assert code in readme, f"the README's refusal table lost {code}"

    def test_the_readme_says_202_and_not_201_for_a_document(self, readme: str) -> None:
        """ADR 0015 made that a statement rather than a detail.

        `202` says the service has taken responsibility and not finished; `201`
        would claim the document is created and done, which is what the whole
        outbox exists to avoid promising.
        """
        assert "`202`, never `201`" in readme, (
            "the README no longer explains why a document is 202 and not 201"
        )
