"""Everything the service needs told to it from outside.

`ARCHITECTURE.md` names this file and its mechanism: "settings via Pydantic
Settings". The value of that over reading `os.environ` by hand is not brevity —
it is that **a missing or malformed setting stops the process from starting**
rather than surfacing as a failure on the first request that needed it.
"""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """The service's configuration, read from the environment or a `.env` file.

    `extra="forbid"` so that a misspelled variable is an error rather than a
    setting that silently keeps its default — the failure mode configuration is
    worst at.
    """

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="forbid"
    )

    database_url: str = Field(
        description=(
            "A libpq connection URL, as psycopg and psql accept it:"
            " postgresql://user:password@host:port/database"
        )
    )
    log_level: str = "INFO"
