import asyncio
import re
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from linkedin_agent import LinkedInAgent


class FakeButton:
    def __init__(self, text="Next", enabled=True):
        self.text = text
        self.enabled = enabled
        self.clicked = False

    async def is_visible(self):
        return True

    async def is_disabled(self):
        return not self.enabled

    async def scroll_into_view_if_needed(self, timeout=None):
        return None

    async def click(self, timeout=None, force=False):
        self.clicked = True

    async def dispatch_event(self, event):
        self.clicked = True

    async def inner_text(self):
        return self.text

    async def get_attribute(self, name):
        if name == "aria-label":
            return self.text
        return ""

    def nth(self, i):
        return self


class FakeButtonLocator:
    def __init__(self, button):
        self.button = button

    async def count(self):
        return 1

    def nth(self, i):
        return self.button


class FakeRoot:
    def __init__(self, button):
        self.button = button

    def get_by_role(self, role, name=None):
        if role == "button" and name is not None:
            pattern = getattr(name, "pattern", "")
            if re.search(r"next|continue|review", pattern, re.I):
                return FakeButtonLocator(self.button)
        return FakeButtonLocator(self.button)

    def locator(self, selector):
        if "button" in selector:
            return FakeButtonLocator(self.button)
        return FakeButtonLocator(self.button)


class FakePage:
    def __init__(self):
        self.button = FakeButton("Next")
        self.root = FakeRoot(self.button)

    def locator(self, selector):
        return FakeLocator(self.root)

    async def wait_for_timeout(self, ms):
        await asyncio.sleep(0)


class FakeLocator:
    def __init__(self, obj):
        self.obj = obj

    async def count(self):
        return 1

    @property
    def last(self):
        return self

    def nth(self, i):
        return self.obj

    def get_by_role(self, role, name=None):
        return self.obj.get_by_role(role, name=name)

    def locator(self, selector):
        return self.obj.locator(selector)


def test_click_next_accepts_successful_native_next_click_without_body_diff():
    agent = LinkedInAgent()
    page = FakePage()
    result = asyncio.run(agent._click_next(page, final_allowed=False))
    assert result is True
    assert page.button.clicked is True


def test_easy_apply_wait_hook_exists():
    src = (HERE / "linkedin_agent.py").read_text(encoding="utf-8")
    assert "async def _wait_for_easy_apply_surface" in src
    assert "await self._wait_for_easy_apply_surface(page)" in src
