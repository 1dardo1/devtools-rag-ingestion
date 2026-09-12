"""The PostgreSQL adapters: documents and collections, over psycopg 3.

ADR 0010 chose psycopg 3 with SQL written by hand; ADR 0012 records the schema
these queries run against. Grouped by technology rather than spread flat across
`infrastructure`, so that "swap the database" is a directory rather than a
search.

**Every repository here is handed a connection and never commits.** Both points
are load-bearing, and `document_repository` says why.
"""
