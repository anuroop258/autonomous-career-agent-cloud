"""Compatibility import for the canonical form observer/reasoner/filler.

All ATS forms use ``src.application.common.ai_form_engine.AIFormEngine`` so
the same question reaches the same profile reasoner and verification logic,
independent of the platform that opened the external page.
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.application.common.ai_form_engine import AIFormEngine

__all__ = ["AIFormEngine"]
