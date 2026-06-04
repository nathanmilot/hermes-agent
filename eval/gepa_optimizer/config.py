"""GEPA config integration with Hermes config system.

Reads the `gepa` section from ~/.hermes/config.yaml to determine whether
GEPA-based optimizations are enabled.
"""
import os
from typing import Optional


def is_gepa_enabled() -> bool:
    """Check whether GEPA optimization is enabled in hermes config.
    
    Reads `gepa.enabled` from config.yaml. Defaults to True if not set.
    """
    try:
        from hermes_cli.config import load_config
        cfg = load_config()
        gepa_cfg = cfg.get("gepa", {})
        if isinstance(gepa_cfg, dict):
            return gepa_cfg.get("enabled", True)
        return True
    except Exception:
        # If config can't be loaded, default to enabled
        return True


def require_gepa_enabled():
    """Raise if GEPA is disabled in config. Use as a guard in optimization entry points."""
    if not is_gepa_enabled():
        raise RuntimeError(
            "GEPA optimization is disabled. Set gepa.enabled: true in "
            "~/.hermes/config.yaml to enable."
        )
