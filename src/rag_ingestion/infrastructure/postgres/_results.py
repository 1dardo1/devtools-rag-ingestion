"""Reading a result that the database guarantees but the type checker cannot."""

import psycopg
from psycopg.rows import TupleRow

_NO_ROW = "A query that must return exactly one row returned none."


def exactly_one_row(cursor: psycopg.Cursor[TupleRow]) -> TupleRow:
    """Return the single row of an aggregate or `EXISTS` query.

    `SELECT count(*)` and `SELECT EXISTS (...)` always return exactly one row,
    but `fetchone()` is typed `TupleRow | None` because most queries do not.
    Something has to close that gap, and the two honest options are to raise or
    to invent a value.

    Raising wins. Inventing one means a `count` of zero or an `EXISTS` of false
    where the truth is that the database did something impossible — and a
    deduplication check that silently answers "not present" is the one failure
    this service most needs not to have.

    `assert` would be the usual idiom and is unavailable: ADR 0006 enabled
    `ruff`'s `S` family, which forbids it outside tests, and an assertion
    stripped by `-O` is the wrong mechanism for a check that must hold in
    production.
    """
    row = cursor.fetchone()
    if row is None:
        raise RuntimeError(_NO_ROW)
    return row
