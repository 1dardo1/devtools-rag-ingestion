from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic.config import Config
from testcontainers.community.postgres import PostgresContainer

# `postgres:16` rather than `postgres:latest`. A test suite whose result
# depends on when it was run is not a test suite, and `latest` moves.
_IMAGE = "postgres:16"

_ALEMBIC_INI = Path(__file__).resolve().parents[2] / "alembic.ini"


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    # `testcontainers.postgres` is deprecated in favour of
    # `testcontainers.community.postgres`; importing the old path emits a
    # DeprecationWarning. `driver=None` asks for a plain `postgresql://` URL:
    # the default is `psycopg2`, which this project does not install, and
    # psycopg 3 wants the URL without a SQLAlchemy driver suffix anyway.
    with PostgresContainer(_IMAGE, driver=None) as container:
        yield container.get_connection_url()


@pytest.fixture
def alembic_config(postgres_url: str) -> Config:
    """Alembic pointed at the throwaway database, via the real `alembic.ini`.

    The checked-in file rather than a `Config` built in the test, so that a
    mistake in `alembic.ini` fails here instead of in production. It leaves
    `sqlalchemy.url` empty on purpose; supplying it here is the mechanism
    `env.py` documents for a caller that already knows which database it means.
    """
    config = Config(_ALEMBIC_INI)
    config.set_main_option("sqlalchemy.url", _as_sqlalchemy_url(postgres_url))
    return config


def _as_sqlalchemy_url(url: str) -> str:
    return url.replace("postgresql://", "postgresql+psycopg://", 1)
