"""Assembling the application, without deciding what it is wired to.

`create_app` returns a FastAPI instance with the routes and the error handling
in place and **no dependency satisfied**. That is the division
`docs/BUILD-PLAN.md` asks for: the web layer and the storage chain meet for the
first time at 4.5.

A factory rather than a module-level `app`. A module-level instance is built on
import, which makes importing this module a side effect — two tests wanting
differently wired applications would fight over one object, and `uvicorn`
accepts a factory anyway.
"""

from fastapi import FastAPI

from rag_ingestion.api import error_handling
from rag_ingestion.api.routes import router

_TITLE = "Devtools RAG — ingestion"
_DESCRIPTION = (
    "The write path: accepts documents, enforces the ingestion rules, and"
    " records each one together with the announcement that it arrived."
)


def create_app() -> FastAPI:
    """Build the application. Dependencies are left for the composition root."""
    app = FastAPI(title=_TITLE, description=_DESCRIPTION, version="0.1.0")
    error_handling.register(app)
    app.include_router(router)
    return app
