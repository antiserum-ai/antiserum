from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
TOY_DIR = REPO_ROOT / "corpus" / "toy"
FEED_PATH = REPO_ROOT / "feed" / "signatures.jsonl"


@pytest.fixture
def toy_dir() -> Path:
    return TOY_DIR


@pytest.fixture
def feed_path() -> Path:
    return FEED_PATH
