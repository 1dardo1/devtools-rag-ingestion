"""Create the initial schema.

Revision ID: 0001
Revises:
Create Date: 2026-09-09

Three tables: `collections`, `documents`, `outbox`. ADR 0012 records why each
column, constraint and index is what it is, and names what was rejected.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CREATE_COLLECTIONS = """
CREATE TABLE collections (
    collection_id uuid PRIMARY KEY,
    name          text NOT NULL,

    -- `Collection` strips surrounding whitespace and refuses a blank name.
    CONSTRAINT collections_name_is_not_blank CHECK (name <> ''),

    -- The guarantee behind `CollectionRepository.exists_with_name`, which
    -- says in its own docstring that it is the legibility half of the rule
    -- and that Phase 4 closes the window with this index.
    --
    -- Case-sensitive, because `Collection` is: it strips, it does not fold.
    -- An index that treated "Docs" and "docs" as one name would enforce a
    -- rule the domain does not have.
    CONSTRAINT collections_name_is_unique UNIQUE (name)
)
"""

_CREATE_DOCUMENTS = """
CREATE TABLE documents (
    document_id     uuid        PRIMARY KEY,
    collection_id   uuid        NOT NULL REFERENCES collections (collection_id),
    content_hash    text        NOT NULL,
    content         bytea       NOT NULL,
    size_in_bytes   bigint      NOT NULL,
    status          text        NOT NULL,
    source_library  text        NOT NULL,
    doc_type        text        NOT NULL,
    library_version text,
    source_url      text,
    ingested_at     timestamptz NOT NULL,

    -- `ContentHash` accepts exactly 64 lowercase hex digits.
    CONSTRAINT documents_content_hash_is_a_sha256_digest
        CHECK (content_hash ~ '^[0-9a-f]{64}$'),

    -- `Document.__post_init__` refuses a negative size.
    CONSTRAINT documents_size_in_bytes_is_not_negative
        CHECK (size_in_bytes >= 0),

    -- The one constraint here that goes beyond what the domain states.
    -- `IngestDocument` computes the size from the very bytes it stores, so
    -- the two can only disagree through a bug; this makes that bug loud
    -- instead of silent. ADR 0012 states the cost.
    CONSTRAINT documents_size_in_bytes_matches_content
        CHECK (size_in_bytes = octet_length(content)),

    -- The four members of `DocumentStatus`, enumerated because another
    -- constraint below depends on this vocabulary being spelled correctly.
    CONSTRAINT documents_status_is_known
        CHECK (status IN ('pending', 'processing', 'indexed', 'failed')),

    -- `Metadata` requires `source_library` and `doc_type`, and rejects a
    -- blank string for an optional field that is present at all: absence is
    -- said with NULL. A CHECK is not applied to a NULL, so these three cover
    -- the required and the optional fields alike.
    CONSTRAINT documents_source_library_is_not_blank
        CHECK (source_library <> ''),
    CONSTRAINT documents_doc_type_is_not_blank
        CHECK (doc_type <> ''),
    CONSTRAINT documents_library_version_is_not_blank
        CHECK (library_version <> ''),
    CONSTRAINT documents_source_url_is_not_blank
        CHECK (source_url <> '')
)
"""

# The schema half of `DocumentRepository.exists_with_content_hash`, which says
# a failed document does not count and points here. Partial, so that a failed
# attempt does not block the resubmission that `Document.mark_failed` promises
# will recover it.
_CREATE_LIVE_CONTENT_INDEX = """
CREATE UNIQUE INDEX documents_live_content_is_unique_per_collection
    ON documents (collection_id, content_hash)
    WHERE status <> 'failed'
"""

# `count_in_collection` counts every document a collection holds, failed ones
# included, so the partial index above cannot serve it. This one also gives
# the foreign key an index, which PostgreSQL does not create by itself.
_CREATE_COLLECTION_INDEX = """
CREATE INDEX documents_by_collection ON documents (collection_id)
"""

_CREATE_OUTBOX = """
CREATE TABLE outbox (
    outbox_id    bigint      GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    event_type   text        NOT NULL,
    payload      jsonb       NOT NULL,
    occurred_at  timestamptz NOT NULL,
    published_at timestamptz,

    CONSTRAINT outbox_event_type_is_not_blank CHECK (event_type <> '')
)
"""

# What the relay reads: the unpublished rows, oldest first. Partial, so the
# index holds only the backlog rather than every event ever published — which
# is the difference between an index that stays small and one that grows
# without limit.
_CREATE_BACKLOG_INDEX = """
CREATE INDEX outbox_unpublished ON outbox (outbox_id) WHERE published_at IS NULL
"""


def upgrade() -> None:
    """Apply this revision."""
    op.execute(_CREATE_COLLECTIONS)
    op.execute(_CREATE_DOCUMENTS)
    op.execute(_CREATE_LIVE_CONTENT_INDEX)
    op.execute(_CREATE_COLLECTION_INDEX)
    op.execute(_CREATE_OUTBOX)
    op.execute(_CREATE_BACKLOG_INDEX)


def downgrade() -> None:
    """Undo this revision.

    `documents` before `collections`, because the foreign key points that way.
    The indexes go with their tables and need no statement of their own.
    """
    op.execute("DROP TABLE outbox")
    op.execute("DROP TABLE documents")
    op.execute("DROP TABLE collections")
