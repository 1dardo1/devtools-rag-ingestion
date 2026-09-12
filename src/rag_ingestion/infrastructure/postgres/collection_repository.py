"""Collections in PostgreSQL."""

from dataclasses import dataclass

import psycopg
from psycopg.rows import TupleRow

from rag_ingestion.domain.collection import Collection
from rag_ingestion.domain.collection_id import CollectionId
from rag_ingestion.infrastructure.postgres._results import exactly_one_row

_INSERT = "INSERT INTO collections (collection_id, name) VALUES (%s, %s)"

_SELECT = "SELECT collection_id, name FROM collections WHERE collection_id = %s"

_EXISTS_WITH_NAME = "SELECT EXISTS (SELECT 1 FROM collections WHERE name = %s)"


@dataclass(frozen=True, slots=True)
class PostgresCollectionRepository:
    """Where collections are kept, for real.

    Takes a connection and never commits, for the same reasons as
    `PostgresDocumentRepository` — and for one more that is specific to it.
    `IngestDocument` reads a collection and writes a document; handing both
    repositories the same connection is what lets those be one transaction
    rather than two, so that a collection cannot be deleted out from under a
    document mid-ingestion.
    """

    connection: psycopg.Connection[TupleRow]

    def add(self, collection: Collection) -> None:
        """Store a newly created collection."""
        self.connection.execute(
            _INSERT, (collection.collection_id.value, collection.name)
        )

    def get(self, collection_id: CollectionId) -> Collection | None:
        """Retrieve a collection, or `None` when there is no such collection."""
        row = self.connection.execute(_SELECT, (collection_id.value,)).fetchone()
        if row is None:
            return None
        return Collection(collection_id=CollectionId(row[0]), name=row[1])

    def exists_with_name(self, name: str) -> bool:
        """Answer whether a collection already goes by this name.

        Compared exactly as stored, with no `lower()` and no `trim()`. The port
        promises the name arrives already stripped because `Collection`
        normalises on construction, and `Collection` does not fold case — so
        folding it here would enforce a uniqueness rule the domain does not
        have, and would disagree with the unique constraint backing it.
        """
        row = exactly_one_row(self.connection.execute(_EXISTS_WITH_NAME, (name,)))
        return bool(row[0])
