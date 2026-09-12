from uuid import UUID, uuid4

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.rows import TupleRow

# The row type `psycopg.connect` hands back by default. Spelled once, because
# the alternative is the same eighteen characters on every signature below.
type Connection = psycopg.Connection[TupleRow]

pytestmark = pytest.mark.integration

_LIVE_CONTENT_INDEX = "documents_live_content_is_unique_per_collection"
_TABLES = frozenset({"collections", "documents", "outbox"})

_INSERT_DOCUMENT = """
INSERT INTO documents (
    document_id, collection_id, content_hash, content, size_in_bytes,
    status, source_library, doc_type, library_version, source_url, ingested_at
) VALUES (%s, %s, %s, %s, %s, %s, 'fastapi', 'reference', NULL, NULL, now())
"""

_CONTENT = b"the same bytes every time"
_HASH = "d0f8ee0e5cf3f0f1e17a7f5b0d1a9e0e0f2f4c1a3b5d7e9f0a1b2c3d4e5f6a7b"


def _table_names(connection: Connection) -> set[str]:
    rows = connection.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
    ).fetchall()
    return {str(row[0]) for row in rows}


def _add_collection(connection: Connection, name: str) -> UUID:
    collection_id = uuid4()
    connection.execute(
        "INSERT INTO collections (collection_id, name) VALUES (%s, %s)",
        (collection_id, name),
    )
    return collection_id


def _add_document(
    connection: Connection,
    collection_id: UUID,
    status: str,
    content_hash: str = _HASH,
) -> UUID:
    document_id = uuid4()
    connection.execute(
        _INSERT_DOCUMENT,
        (document_id, collection_id, content_hash, _CONTENT, len(_CONTENT), status),
    )
    return document_id


def test_upgrade_creates_the_three_tables(
    migrated: Connection,
) -> None:
    assert _table_names(migrated) >= _TABLES


def test_downgrade_removes_them_again(
    alembic_config: Config, migrated: Connection
) -> None:
    command.downgrade(alembic_config, "base")

    assert not _TABLES & _table_names(migrated)


def test_a_failed_document_does_not_block_resubmitting_its_content(
    migrated: Connection,
) -> None:
    collection_id = _add_collection(migrated, "fastapi-docs")
    _add_document(migrated, collection_id, "failed")

    _add_document(migrated, collection_id, "pending")


def test_two_failed_attempts_at_the_same_content_may_coexist(
    migrated: Connection,
) -> None:
    collection_id = _add_collection(migrated, "fastapi-docs")
    _add_document(migrated, collection_id, "failed")

    _add_document(migrated, collection_id, "failed")


@pytest.mark.parametrize("status", ["pending", "processing", "indexed"])
def test_a_second_live_copy_of_the_same_content_is_refused(
    migrated: Connection, status: str
) -> None:
    collection_id = _add_collection(migrated, "fastapi-docs")
    _add_document(migrated, collection_id, status)

    with pytest.raises(psycopg.errors.UniqueViolation, match=_LIVE_CONTENT_INDEX):
        _add_document(migrated, collection_id, "pending")


def test_the_same_content_may_live_in_two_collections(
    migrated: Connection,
) -> None:
    first = _add_collection(migrated, "fastapi-docs")
    second = _add_collection(migrated, "pydantic-docs")
    _add_document(migrated, first, "indexed")

    _add_document(migrated, second, "indexed")


def test_a_collection_name_may_not_repeat(
    migrated: Connection,
) -> None:
    _add_collection(migrated, "fastapi-docs")

    with pytest.raises(psycopg.errors.UniqueViolation):
        _add_collection(migrated, "fastapi-docs")


def test_a_recorded_size_that_contradicts_the_content_is_refused(
    migrated: Connection,
) -> None:
    collection_id = _add_collection(migrated, "fastapi-docs")

    contradiction = "size_in_bytes_matches_content"
    with pytest.raises(psycopg.errors.CheckViolation, match=contradiction):
        migrated.execute(
            _INSERT_DOCUMENT,
            (uuid4(), collection_id, _HASH, _CONTENT, len(_CONTENT) + 1, "pending"),
        )


def test_an_unknown_status_is_refused(
    migrated: Connection,
) -> None:
    collection_id = _add_collection(migrated, "fastapi-docs")

    with pytest.raises(psycopg.errors.CheckViolation, match="status_is_known"):
        _add_document(migrated, collection_id, "INDEXED")


def test_a_content_hash_that_is_not_a_digest_is_refused(
    migrated: Connection,
) -> None:
    collection_id = _add_collection(migrated, "fastapi-docs")

    with pytest.raises(psycopg.errors.CheckViolation, match="sha256_digest"):
        _add_document(migrated, collection_id, "pending", content_hash="not-a-digest")


def test_a_document_needs_a_collection_that_exists(
    migrated: Connection,
) -> None:
    with pytest.raises(psycopg.errors.ForeignKeyViolation):
        _add_document(migrated, uuid4(), "pending")
