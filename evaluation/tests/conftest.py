"""Use the frozen user engine only when the backend package is unavailable."""

import importlib.util
import sys
from pathlib import Path

if importlib.util.find_spec("ahe_beta") is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "harness/user_engine"))
