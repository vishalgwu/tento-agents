"""Make the uninstalled Phase-1 API source importable in its test suite."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
