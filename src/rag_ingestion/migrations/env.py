"""How Alembic reaches the database.

The stock file that `alembic init` writes has been cut down to what this
service actually does. There is no `target_metadata`, because ADR 0010 chose
hand-written SQL and no declared models: `autogenerate` has nothing to diff
against and is not available here.

What remains is the one question the stock file leaves open — where the
database URL comes from. See `_database_url`.
"""

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

_URL_ENVIRONMENT_VARIABLE = "DATABASE_URL"
_URL_OPTION = "sqlalchemy.url"
_NO_URL = (
    "No database URL. Set the DATABASE_URL environment variable, or set "
    "sqlalchemy.url on the Alembic config before running migrations."
)

config = context.config

if config.config_file_name is not None:
    # `disable_existing_loggers=False`, unlike the stock file. Migrations are
    # run in-process by the integration tests, and will be by whatever runs
    # them at deploy time; silencing every logger the host had already set up
    # is not this file's business.
    fileConfig(config.config_file_name, disable_existing_loggers=False)


def _database_url() -> str:
    """Find the database to migrate, preferring an explicitly configured URL.

    Two callers, two mechanisms. A person or a container runs `alembic upgrade
    head` with `DATABASE_URL` set, which is how the Phase 5 image will do it.
    A test already holds the URL of the database it just started and sets it on
    the config object directly, which keeps it out of the process environment
    where a later test could inherit it.

    The configured URL wins, so a caller that has said which database it means
    cannot be overridden by an environment variable it did not set.

    `alembic.ini` leaves `sqlalchemy.url` empty rather than naming a database.
    A URL in a checked-in file is a credential in version control the first
    time someone adds a password to it.

    **`DATABASE_URL` holds a plain libpq URL and the dialect is added here.**
    One variable has to serve two readers — this, and the service's `Settings` —
    and they cannot share the SQLAlchemy form: `psycopg.connect` rejects
    `postgresql+psycopg://` outright with `missing "=" after ...`. The libpq
    form is the one every PostgreSQL tool already accepts, so it is the
    canonical shape and SQLAlchemy's prefix is this file's problem. ADR 0017.
    """
    configured = config.get_main_option(_URL_OPTION, default="")
    if configured:
        return _with_dialect(configured)
    from_environment = os.environ.get(_URL_ENVIRONMENT_VARIABLE, "")
    if from_environment:
        return _with_dialect(from_environment)
    raise RuntimeError(_NO_URL)


def _with_dialect(url: str) -> str:
    """Name psycopg as the driver, unless a caller already named one."""
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def run_migrations_offline() -> None:
    """Emit the migrations as SQL text, without connecting to anything.

    `alembic upgrade head --sql` prints what it would do. Useful when the
    database is changed by someone holding credentials this process does not.
    """
    context.configure(
        url=_database_url(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Connect to the database and apply the migrations.

    `NullPool` because this process opens one connection, uses it once and
    exits. A pool would be machinery for a lifetime that does not exist.
    """
    section = config.get_section(config.config_ini_section, {})
    section[_URL_OPTION] = _database_url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )

    with connectable.connect() as connection:
        context.configure(connection=connection)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
