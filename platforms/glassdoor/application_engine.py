"""Glassdoor application engine facade. Native Easy Apply opens Indeed SmartApply; external routes are skipped after Glassdoor's preference modal is dismissed."""
from pathlib import Path
import sys
PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
try:
    from .glassdoor_agent import GlassdoorAgent
except ImportError:
    # When this facade is loaded directly from a file, use the fully-qualified
    # package path so Python does not accidentally reuse another platform's
    # bare ``glassdoor_agent`` / ``storage`` module from sys.modules.
    from platforms.glassdoor.glassdoor_agent import GlassdoorAgent

class GlassdoorApplicationEngine:
    PLATFORM = "glassdoor"
    WORKFLOW = "Glassdoor Easy Apply -> Indeed SmartApply native flow; external Apply -> Skip for now -> leave external destination open"
    def __init__(self, agent=None):
        self.agent = agent or GlassdoorAgent()
    async def run(self, context, search_url):
        return await self.agent.run_search(context, search_url)
