"""Platform-specific Naukri application engine facade.

The existing NaukriAgent remains the implementation of the proven workflow.
This facade makes the platform boundary explicit without replacing its logic.
"""

from naukri_agent import NaukriAgent


class NaukriApplicationEngine:
    PLATFORM = "naukri"
    WORKFLOW = "native Naukri flow + external company-site flow"

    def __init__(self, agent=None):
        self.agent = agent or NaukriAgent()

    async def run(self, context, search_url):
        return await self.agent.run_with_context(context, search_url)
