import importlib
from pathlib import Path

_module = importlib.util.spec_from_file_location(
    "logger_engine",
    Path(__file__).parent / "logger-engine.py",
)
_mod = importlib.util.module_from_spec(_module)
_module.loader.exec_module(_mod)
LoggerEngine = _mod.LoggerEngine
