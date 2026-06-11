"""Pytest configuration: add the src/ directory to sys.path so the package
can be imported without a full install (``pip install -e .``).
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent.parent / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))
