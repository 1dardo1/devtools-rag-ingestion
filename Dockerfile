# The ingestion service as an image. ADR 0019.
#
# Two stages. The first resolves and installs; the second runs. `uv` exists only
# in the first, so a build tool never ships to production, and the runtime layer
# holds the virtual environment and the source and nothing else.
#
# `python:3.14-slim` rather than Alpine, and that was settled on evidence rather
# than size: `psycopg[binary]` is a **manylinux** wheel with libpq bundled
# inside it. Alpine is musl, where that wheel does not exist, so `uv` would fall
# back to building psycopg from source — needing a compiler and `libpq-dev`,
# producing a *larger* image more slowly, and throwing away the binary wheel ADR
# 0010 deliberately chose.

# ---------------------------------------------------------------- build stage
FROM python:3.14-slim AS build

# Pinned, and pinned to **the version `.github/workflows/ci.yml` pins**. A
# different resolver in the image than in CI is two answers to "what does
# `uv.lock` mean"; `:latest` would be a third, arriving whenever.
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /usr/local/bin/uv

# Copy rather than hard-link: the cache and the target environment are on
# different layers, where linking cannot work.
ENV UV_LINK_MODE=copy
# Never fetch a Python. The base image already has 3.14, and `uv` downloading its
# own would make the image's interpreter and the locked one two different things.
ENV UV_PYTHON_DOWNLOADS=never
ENV UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

# Dependencies before the source, in their own layer. They change when
# `uv.lock` changes; the source changes on every commit. Inverting the two means
# every edit to a docstring re-resolves and re-downloads everything.
#
# `--no-install-project` installs only the dependencies on this pass.
# `--locked` fails rather than quietly re-resolving, so an image can never be
# built from a dependency set the lockfile does not describe.
# `--no-dev` leaves the test toolchain out: `pytest`, `mypy`, `ruff` and
# `testcontainers` have no business in a runtime image.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

# Then the project. `alembic.ini` is here because ADR 0010 made `alembic` a
# runtime dependency precisely so this image can run `alembic upgrade head`, and
# `README.md` because `pyproject.toml` names it as the project's readme, which
# the build backend reads.
COPY alembic.ini README.md ./
COPY src/ ./src/
RUN uv sync --locked --no-dev

# -------------------------------------------------------------- runtime stage
FROM python:3.14-slim AS runtime

# A non-root user, created before anything is copied so the copies can be owned
# by it. `--no-create-home` because nothing here writes to a home directory; if
# something ever needs to, that should be a volume and a decision rather than a
# side effect of this line.
RUN useradd --system --no-create-home --shell /usr/sbin/nologin ingestion

ENV PATH=/app/.venv/bin:$PATH
# Buffered stdout in a container means logs that arrive late, or never when the
# process dies holding them. ADR 0016 made stdout the log; this keeps it honest.
ENV PYTHONUNBUFFERED=1
# No `.pyc` written at runtime: they would land in the image's layers, written by
# a user who should not be writing anything.
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY --from=build --chown=ingestion:ingestion /app /app

USER ingestion

EXPOSE 8000

# **Migrations are not run here, and that is a decision rather than an omission.**
# ADR 0019: every replica starting at once would race to apply the same revision,
# and a migration that fails during startup becomes a crashloop instead of a
# deployment that visibly failed. `alembic upgrade head` is available in this
# image — run it as its own step, against the database, once.
#
# `--factory`, because `main:build` returns an application rather than being one;
# `api/app.py` says why it is a factory at all. `--host 0.0.0.0` so the port is
# reachable from outside the container.
#
# One worker, and not as a default left unexamined: more than one is an
# optimization, and `ARCHITECTURE.md` principle 10 says not before measurement.
# The orchestrator scales replicas, which is the same lever one level up without
# also putting a process manager inside the image.
CMD ["uvicorn", "rag_ingestion.main:build", "--factory", "--host", "0.0.0.0", "--port", "8000"]
