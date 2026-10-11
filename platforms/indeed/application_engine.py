"""Platform-specific Indeed application engine facade.

Indeed keeps its own native Apply and external-routing behavior.  Do not use
LinkedIn/Naukri application assumptions here.
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

try:
    from .indeed_agent import IndeedAgent
except ImportError:  # direct script execution from the platform directory
    from indeed_agent import IndeedAgent


class IndeedApplicationEngine:
    PLATFORM = "indeed"
    WORKFLOW = "Indeed native Apply -> application form -> external fallback only when exposed"

    def __init__(self, agent=None):
        self.agent = agent or IndeedAgent()

    async def run(self, context, search_url):
        return await self.agent.run_search(context, search_url)
