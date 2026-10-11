"""Compatibility adapter for the one canonical Naukri workflow.

LinkedIn does not own an alternative Naukri implementation. Keeping this
adapter thin prevents an older external-Apply or profile-mapping path from
silently diverging from the canonical workflow.
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
