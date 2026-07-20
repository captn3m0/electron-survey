"""Load a processor module from steps/ by filename.

The step files use dotted / hyphenated names (e.g. ``github.com.py``,
``aur-version.py``) that aren't importable as normal modules, so tests load
them the same way the runner does.
"""

import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_step(filename: str):
    path = ROOT / "steps" / filename
    mod_name = "step_" + path.stem.replace(".", "_").replace("-", "_")
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
