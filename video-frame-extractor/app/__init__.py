import sys
from pathlib import Path

_pkg = Path(__file__).resolve().parents[2] / "tsumtsum-analyze"
_root = str(_pkg)
if _root not in sys.path:
    sys.path.insert(0, _root)
