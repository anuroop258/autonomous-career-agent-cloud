"""Compatibility adapter for the one canonical Naukri workflow.

This module used to be a copied Naukri implementation and could therefore
retain obsolete external-routing behavior after the root workflow had been
fixed. It exports the root workflow instead of owning a second browser or
answer-state machine.
"""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SPEC = spec_from_file_location("canonical_naukri_agent", PROJECT_ROOT / "naukri_agent.py")
if _SPEC is None or _SPEC.loader is None:
    raise ImportError("Could not load the canonical Naukri agent.")
_MODULE = module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

NaukriAgent = _MODULE.NaukriAgent
connect_to_real_chrome_only = _MODULE.connect_to_real_chrome_only

__all__ = ["NaukriAgent", "connect_to_real_chrome_only"]
