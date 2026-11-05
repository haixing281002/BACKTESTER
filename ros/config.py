# Quant AI Researcher by Harshil Pahuja
"""Fund-level settings the code reads and never types: house cost, AUM, the mandate and the gate's thresholds."""
from __future__ import annotations

import os
from typing import Any

import yaml

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_DIR = os.environ.get("LIGHTYEAR_CONFIG_DIR") or os.path.join(REPO, "config")


def _load(name: str) -> dict[str, Any]:
    with open(os.path.join(CONFIG_DIR, name), encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def house_cost_bp() -> float:
    return float(_load("costs.yaml")["house_round_trip_bp"])


def fund() -> dict[str, Any]:
    return _load("fund.yaml")


def mandate() -> dict[str, Any]:
    return _load("mandate.yaml")


def gate_thresholds() -> dict[str, Any]:
    return _load("gate_thresholds.yaml")
