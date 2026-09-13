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
            "A libpq connection URL, as psycopg and psql accept it —"
            " scheme, optional credentials, host, port and database."
            " For example postgresql://postgres@localhost:5432/ingestion;"
            " a deployment's will also carry a password."
        )
    )
    """The example here is deliberately password-free.

    It used to spell the shape out with a literal `user:password@` in it, which
    `test_no_secret_is_committed` flagged on its first run — correctly, because
    that is exactly the shape of the one credential this service could leak, and a
    guard that makes an exception for "obvious placeholders" is a guard that can
    be talked into ignoring the real thing. The example now matches what
    `compose.yaml` actually runs, and says in prose what it no longer shows.
    """
    log_level: str = "INFO"

    max_body_bytes: int = 7 * 1024 * 1024
    """The largest request body the service will read, in bytes on the wire.

    Deliberately **not** the domain's `max_document_size_in_bytes`, and larger
    than it. That one is 5 MiB of decoded content; base64 inside JSON turns the
    same document into roughly 6.7 MiB on the wire, so a cap set to the domain's
    figure would refuse documents the domain accepts. 7 MiB leaves the base64
    expansion plus room for the metadata around it.

    A plain number rather than one derived from the domain's limit, because a
    reader of a configuration file should see the figure. What keeps the two from
    drifting apart is a test —
    `test_the_body_cap_cannot_refuse_a_document_the_domain_accepts` — which fails
    if either moves without the other, the same way two other rules in this
    service are held by guards rather than by review.
    """
