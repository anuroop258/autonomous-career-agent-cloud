"""Platform-specific LinkedIn application engine facade.

LinkedIn has its own Easy Apply, external Apply redirect/interstitial, and
search-controller lifecycle.  Its application behavior must not be inferred
from the Indeed or Naukri engines.
"""

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))

try:
    from .src.application.linkedin.linkedin_agent import LinkedInAgent
except ImportError:  # direct script execution from the platform directory
    from linkedin_agent import LinkedInAgent


class LinkedInApplicationEngine:
    PLATFORM = "linkedin"
    WORKFLOW = "LinkedIn match -> route -> Easy Apply or external application"

    def __init__(self, agent=None):
        self.agent = agent or LinkedInAgent()

    async def run(self, context, search_url):
        return await self.agent.run_with_context(context, search_url)
