import sys
from pathlib import Path

import pandas as pd
import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> pd.DataFrame:
    """Load one of the reference datasets (§8 validation strategy)."""
    return pd.read_csv(FIXTURES / name)


@pytest.fixture
def reference():
    return load
