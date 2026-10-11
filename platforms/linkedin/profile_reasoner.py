"""Compatibility import for the canonical profile-grounded reasoner."""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.application.common.profile_reasoner import ProfileReasoner

__all__ = ["ProfileReasoner"]
