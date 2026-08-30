"""The first test in the repository, and it is not a formality.

Under a src layout the test suite runs against the *installed* distribution
rather than the source tree, so importing every package proves that `uv sync`
built and installed the package correctly. A layer missing from the built
artifact fails here rather than in production. See ADR 0003.
"""

import importlib

import pytest

LAYERS = [
    "rag_ingestion",
    "rag_ingestion.api",
    "rag_ingestion.application",
    "rag_ingestion.domain",
    "rag_ingestion.infrastructure",
]


@pytest.mark.parametrize("module_name", LAYERS)
def test_layer_is_importable_from_the_installed_distribution(
    module_name: str,
) -> None:
    module = importlib.import_module(module_name)

    assert module.__doc__, f"{module_name} should document what the layer is for"
