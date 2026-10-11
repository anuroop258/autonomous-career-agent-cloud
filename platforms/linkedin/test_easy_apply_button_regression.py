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


class FakeElement:
    def __init__(self, page, text="Easy Apply", enabled=True, fail_normal=False):
        self.page = page
        self.text = text
        self.enabled = enabled
        self.fail_normal = fail_normal
        self.clicks = []

    async def is_visible(self):
        return True

    async def is_disabled(self):
        return not self.enabled

    async def scroll_into_view_if_needed(self):
        return None

    async def click(self, timeout=None, force=False):
        self.clicks.append((timeout, force))
        if self.fail_normal and not force:
            raise RuntimeError("overlay")
        if self.text.lower().strip() == "easy apply":
            self.page.modal = True

    async def inner_text(self):
        return self.text

    async def get_attribute(self, name):
        if name == "aria-label":
            return self.text
        if name == "title":
            return ""
        return None

    def locator(self, selector):
        if "ancestor-or-self::button" in selector and self.text.lower().strip() == "easy apply":
            return FakeLocator([self])
        return FakeLocator([])

    async def input_value(self):
        return ""


class FakeLocator:
    def __init__(self, elements):
        self.elements = elements

    def nth(self, i):
        return self.elements[i]

    async def count(self):
        return len(self.elements)

    async def all_inner_texts(self):
        return [e.text for e in self.elements]


class FakePage:
    def __init__(self, easy=None, plain_apply=False):
        self.modal = False
        self.easy = easy
        self.plain_apply = plain_apply

    def get_by_role(self, role, name=None):
        if role == "button" and name and re.search(r"Easy\\s*Apply", getattr(name, "pattern", ""), re.I):
            return FakeLocator([self.easy] if self.easy else [])
        return FakeLocator([])

    def get_by_text(self, pattern):
        return FakeLocator([])

    def locator(self, selector):
        if "jobs-easy-apply-modal:visible" in selector or "div[role='dialog']:visible" in selector or "[aria-modal='true']:visible" in selector:
            return FakeLocator([FakeElement(self, "dialog")]) if self.modal else FakeLocator([])
        if selector.startswith("button:visible") or selector.startswith("button[aria-label") or selector.startswith("button.jobs-apply-button"):
            if self.plain_apply:
                return FakeLocator([FakeElement(self, "Apply")])
            if self.easy:
                return FakeLocator([self.easy])
        return FakeLocator([])

    async def wait_for_timeout(self, ms):
        await asyncio.sleep(0)


def test_easy_apply_exact_role_button_is_clicked_and_verified():
    agent = LinkedInAgent()
    page = FakePage(easy=FakeElement(None))
    page.easy.page = page
    result = asyncio.run(agent.click_easy_apply(page))
    assert result is True
    assert page.modal is True
    assert page.easy.clicks


def test_easy_apply_force_click_recovers_from_overlay():
    agent = LinkedInAgent()
    page = FakePage(easy=FakeElement(None, fail_normal=True))
    page.easy.page = page
    result = asyncio.run(agent.click_easy_apply(page))
    assert result is True
    assert any(force for _, force in page.easy.clicks)


def test_plain_apply_label_is_accepted_for_native_route():
    agent = LinkedInAgent()
    page = FakePage(easy=None, plain_apply=True)
    result = asyncio.run(agent.click_easy_apply(page))
    assert result is True


def test_plain_native_apply_label_is_accepted_when_route_is_already_native():
    agent = LinkedInAgent()
    page = FakePage(easy=None, plain_apply=True)
    # Current LinkedIn builds can render the native CTA as plain "Apply".
    # click_easy_apply should accept that once the route detector has already
    # classified it as native.
    result = asyncio.run(agent.click_easy_apply(page))
    assert result is True

