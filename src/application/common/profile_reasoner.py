"""Canonical profile-grounded reasoning service for all platform adapters."""

from pathlib import Path
import importlib.util


PROJECT_ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "canonical_profile_reasoner", PROJECT_ROOT / "profile_reasoner.py"
)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError("Could not load the canonical profile reasoner.")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

ProfileReasoner = _MODULE.ProfileReasoner


__all__ = ["ProfileReasoner"]
