# execution/config.py
from __future__ import annotations
from pathlib import Path
import yaml

_DEFAULT = Path(__file__).with_name("params.yaml")


def load_params(path: str | Path = _DEFAULT) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)
