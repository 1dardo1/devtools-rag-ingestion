"""The domain imports only the standard library and itself.

`CLAUDE.md` states the rule: "The `domain/` package imports nothing external. No
FastAPI, no SQLAlchemy, no Redis client. If an external type seems necessary, a
port is missing." Until this file existed, nothing enforced it. A reviewer had to
notice, and a reviewer reading a diff sees the lines that changed, not the import
that one of them quietly needed.

**Why an allowlist and not a ban list.** `sys.stdlib_module_names` names every
module the interpreter ships, so anything outside it is external by definition,
including packages nobody has thought to forbid yet. A list of forbidden names,
such as ruff's banned-api rule, would only catch the ones somebody remembered.

**What counts as inside.** The standard library and `rag_ingestion.domain`
itself, by absolute or relative import. **The rest of `rag_ingestion` is
outside.** An import from `rag_ingestion.infrastructure` is first-party code but
points the dependency arrow outward, which is the same violation in a different
coat.

**`TYPE_CHECKING` imports count.** A type that appears only in an annotation still
couples the domain to the package that defines it. Hiding the import behind a
guard changes when it runs, not what the domain depends on.

**What this cannot see.** `importlib.import_module("...")` with a string, and
anything a standard-library module loads in turn. Neither occurs in the domain,
and a dynamic import there would be strange enough for review to catch.
"""

import ast
import sys
from pathlib import Path

_DOMAIN = Path(__file__).resolve().parents[3] / "src" / "rag_ingestion" / "domain"
_DOMAIN_PACKAGE = "rag_ingestion.domain"


def _external_imports(source: str) -> list[tuple[int, str]]:
    """Every import in `source` that leaves the standard library and the domain.

    The source is parsed rather than imported, so the check needs none of the
    module's dependencies installed. A module that imports something missing
    still yields its line instead of an `ImportError` that hides which line it
    was.
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names = [node.module]
        else:
            # A relative import (`from . import x`) cannot leave the package.
            continue
        for name in names:
            inside_domain = name == _DOMAIN_PACKAGE or name.startswith(
                f"{_DOMAIN_PACKAGE}."
            )
            in_stdlib = name.partition(".")[0] in sys.stdlib_module_names
            if not (inside_domain or in_stdlib):
                found.append((node.lineno, name))
    return found


def test_the_domain_imports_nothing_external() -> None:
    modules = sorted(_DOMAIN.rglob("*.py"))
    violations = [
        f"{module.relative_to(_DOMAIN.parents[2])}:{line} imports {name}"
        for module in modules
        for line, name in _external_imports(module.read_text(encoding="utf-8"))
    ]

    assert modules, f"found no modules under {_DOMAIN}, so this proves nothing"
    assert not violations, "\n".join(
        ["the domain must import nothing external; a port is missing:", *violations]
    )


def test_the_guard_can_actually_see_an_external_import() -> None:
    """The guard's own test: a check that never fires proves nothing.

    The domain is clean today, so `test_the_domain_imports_nothing_external`
    passes whether the guard works or not. This feeds it the shapes it must
    catch and the shapes it must let through. ADR 0022 is why this exists: the
    secret scanner's first version matched nothing, and only a test like this
    one noticed.
    """
    source = """\
import os
import pydantic
from collections.abc import Callable
from typing import TYPE_CHECKING
from rag_ingestion.domain.errors import DomainError
from rag_ingestion.infrastructure.system_clock import SystemClock
from . import limits
import psycopg.rows

if TYPE_CHECKING:
    from fastapi import Request
"""

    assert _external_imports(source) == [
        (2, "pydantic"),
        (6, "rag_ingestion.infrastructure.system_clock"),
        (8, "psycopg.rows"),
        (11, "fastapi"),
    ]
