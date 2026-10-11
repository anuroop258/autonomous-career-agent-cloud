import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from indeed_agent import IndeedAgent


class FakeLocator:
    def __init__(self, text):
        self.text = text
    async def inner_text(self, timeout=5000):
        return self.text


class FakePage:
    def __init__(self, title, body):
        self._title = title
        self._body = body
    def is_closed(self):
        return False
    async def title(self):
        return self._title
    def locator(self, selector):
        return FakeLocator(self._body)


async def main():
    agent = IndeedAgent()
    cases = [
        (FakePage("Additional Verification Required", "Cloudflare\nRay ID: abc"), True),
        (FakePage("Just a moment...", "Verifying..."), True),
        (FakePage("GenAI Engineer", "Responsibilities include Python and LLM."), False),
    ]
    for page, expected in cases:
        got = await agent.detect_blocker(page)
        assert got is expected, (page._title, got, expected)
    print("Human verification detection regression: PASS")


if __name__ == "__main__":
    asyncio.run(main())
