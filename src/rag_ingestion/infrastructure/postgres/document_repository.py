"""Documents in PostgreSQL.

Implements `DocumentRepository` by having the right methods, not by inheriting
from it — the port is a `Protocol`, per principle 4.3. Nothing in the domain
imports this file.
"""

from dataclasses import dataclass

import psycopg
from psycopg.rows import TupleRow

from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.domain.content_hash import ContentHash
from rag_ingestion.domain.doc_type import DocType
from rag_ingestion.domain.document import Document
from rag_ingestion.domain.document_id import DocumentId
from rag_ingestion.domain.document_status import DocumentStatus
from rag_ingestion.domain.metadata import Metadata
from rag_ingestion.infrastructure.postgres._results import exactly_one_row

_INSERT = """
INSERT INTO documents (
    document_id, collection_id, content_hash, content, size_in_bytes,
    status, source_library, doc_type, library_version, source_url, ingested_at
) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
"""

# `content` is deliberately absent from the column list. ADR 0012 chose to keep
# the bytes on this table on the grounds that TOAST moves large values out of
# line, so a query that does not name the column does not read them — and that
# only holds if the queries actually do not name it. This is the query that
# makes the claim true.
_SELECT = """
SELECT document_id, collection_id, content_hash, size_in_bytes, status,
       source_library, doc_type, library_version, source_url, ingested_at
FROM documents
WHERE document_id = %s
"""

# `status <> %s` with the enum member passed as a parameter, rather than the
# word 'failed' written into the SQL. psycopg adapts a `StrEnum` as text, so
# `DocumentStatus` stays the single place the vocabulary is spelled — which is
# what stops this query and the partial index from drifting apart.
_EXISTS_LIVE_CONTENT = """
SELECT EXISTS (
    SELECT 1 FROM documents
    WHERE collection_id = %s AND content_hash = %s AND status <> %s
)
"""

_COUNT_IN_COLLECTION = "SELECT count(*) FROM documents WHERE collection_id = %s"


@dataclass(frozen=True, slots=True)
class PostgresDocumentRepository:
    """Where documents are kept, for real.

    **It is handed a connection rather than a pool or a URL, and that is the
    most important line in this class.** The single invariant this service
    exists to demonstrate is that a document and its outbox row are written in
    one transaction. That is only possible if the thing writing the document and
    the thing writing the outbox row are on the *same* connection, so the
    connection has to come from outside — from whoever owns the transaction.

    A pool would read better and would quietly make the invariant unachievable:
    each call would borrow its own connection, each would be its own
    transaction, and 4.2 would have nowhere left to stand. That is the rejected
    alternative, and it is rejected on the one thing this service cannot give
    up.

    **It also never commits and never rolls back.** A repository that commits
    has decided where the transaction ends, and that decision belongs to the
    caller. `add` leaves the work pending; the composition root, or the
    unit of work 4.2 may need, says when it becomes durable.
    """

    connection: psycopg.Connection[TupleRow]

    def add(self, document: Document, content: bytes) -> None:
        """Store a document that has passed every rule, with its content.

        One statement, so the record and the bytes cannot be separated by a
        failure in between. The port asks for exactly that.

        A duplicate that slips past `exists_with_content_hash` — two requests
        racing — is refused here by the partial unique index, and surfaces as
        psycopg's `UniqueViolation` rather than a domain error. Translating it
        is error-handling strategy, which `docs/BUILD-PLAN.md` still has open as
        a decision due before 4.5; this adapter does not pre-empt it.
        """
        self.connection.execute(
            _INSERT,
            (
                document.document_id.value,
                document.collection_id.value,
                document.content_hash.value,
                content,
                document.size_in_bytes,
                document.status,
                document.metadata.source_library,
                document.metadata.doc_type,
                document.metadata.library_version,
                document.metadata.source_url,
                document.ingested_at,
            ),
        )

    def get(self, document_id: DocumentId) -> Document | None:
        """Retrieve a document, or `None` when there is no such document.

        The row becomes a `Document` through the domain's own constructors, per
        ADR 0010, so every invariant the domain enforces on the way in is
        enforced again on the way out. A row that the domain would refuse to
        build raises here instead of being handed onward as a valid entity.
        """
        row = self.connection.execute(_SELECT, (document_id.value,)).fetchone()
        return None if row is None else _as_document(row)

    def exists_with_content_hash(
        self, collection_id: CollectionId, content_hash: ContentHash
    ) -> bool:
        """Answer whether this collection holds this content in a live state.

        `EXISTS` rather than a count or a fetched row: the caller asked a
        question, and this lets PostgreSQL stop at the first match.

        Failed documents do not count, which is the port's contract and the
        reason the supporting index is partial.
        """
        row = exactly_one_row(
            self.connection.execute(
                _EXISTS_LIVE_CONTENT,
                (collection_id.value, content_hash.value, DocumentStatus.FAILED),
            )
        )
        return bool(row[0])

    def count_in_collection(self, collection_id: CollectionId) -> int:
        """Count the documents a collection currently holds.

        **Every document, failed ones included.** The port says "currently
        holds", and a failed row still occupies the collection. This is why the
        schema carries a plain index on `collection_id` as well as the partial
        unique one, which cannot serve a count that includes failures.
        """
        row = exactly_one_row(
            self.connection.execute(_COUNT_IN_COLLECTION, (collection_id.value,))
        )
        return int(row[0])


def _as_document(row: TupleRow) -> Document:
    return Document(
        document_id=DocumentId(row[0]),
        collection_id=CollectionId(row[1]),
        content_hash=ContentHash(row[2]),
        size_in_bytes=row[3],
        status=DocumentStatus(row[4]),
        metadata=Metadata(
            source_library=row[5],
            doc_type=DocType(row[6]),
            library_version=row[7],
            source_url=row[8],
        ),
        ingested_at=row[9],
    )
