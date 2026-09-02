"""How much the service is willing to accept."""

from dataclasses import dataclass

from rag_ingestion.domain.errors import InvalidLimitError

_DEFAULT_MAX_DOCUMENT_SIZE_IN_BYTES = 5 * 1024 * 1024
_DEFAULT_MAX_DOCUMENTS_PER_COLLECTION = 10_000


@dataclass(frozen=True, slots=True)
class IngestionLimits:
    """The ceilings ingestion enforces.

    Carried as a value object rather than hard-coded into the rules, so the
    numbers can be supplied from configuration in Phase 4 without the domain
    knowing where they came from. The defaults exist so that a test, or an
    early use case, can construct a policy without inventing figures.

    The defaults are a judgement, not a measurement: 5 MiB comfortably holds
    any single page of developer documentation, and ten thousand documents is
    far more than this corpus needs. Both should be revisited once there is
    real traffic to look at — which, per principle 4.10, is also the first
    moment either could be chosen on evidence.
    """

    max_document_size_in_bytes: int = _DEFAULT_MAX_DOCUMENT_SIZE_IN_BYTES
    max_documents_per_collection: int = _DEFAULT_MAX_DOCUMENTS_PER_COLLECTION

    def __post_init__(self) -> None:
        self._reject_if_not_positive(
            self.max_document_size_in_bytes, "max_document_size_in_bytes"
        )
        self._reject_if_not_positive(
            self.max_documents_per_collection, "max_documents_per_collection"
        )

    @staticmethod
    def _reject_if_not_positive(value: int, limit_name: str) -> None:
        if value <= 0:
            raise InvalidLimitError(limit_name, value)
