"""Loader for code that still imports assertions from the Processing Layer root."""
from pathlib import Path
import importlib.util
import sys

_path = Path(__file__).resolve().parent / "field_assertions" / "assertions.py"
_spec = importlib.util.spec_from_file_location("assertions", _path)
if _spec is None or _spec.loader is None:
    raise ImportError(f"cannot load {_path}")
_mod = importlib.util.module_from_spec(_spec)
sys.modules.setdefault("assertions", _mod)
_spec.loader.exec_module(_mod)
globals().update(_mod.__dict__)
