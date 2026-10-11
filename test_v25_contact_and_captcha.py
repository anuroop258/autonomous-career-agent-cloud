
import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


class DummyPage:
    def __init__(self):
        self.closed = False
        self.sleeps = 0

    def is_closed(self):
        return self.closed

    async def wait_for_timeout(self, ms):
        self.sleeps += 1
        await asyncio.sleep(0)


class DummyElement:
    def __init__(self, *, typ="", name="", element_id="", placeholder="", value=""):
        self.attrs = {
            "type": typ,
            "name": name,
            "id": element_id,
            "placeholder": placeholder,
            "aria-label": "",
        }
        self.value = value
        self.page = DummyPage()

    async def get_attribute(self, key):
        return self.attrs.get(key, "")

    async def input_value(self):
        return self.value

    async def fill(self, value):
        self.value = str(value)

    async def is_visible(self):
        return True

    async def evaluate(self, script):
        if "tagName" in script:
            return "INPUT"
        return ""

    def locator(self, _selector):
        return DummyNode()


class DummyNode:
    async def count(self):
        return 0

    @property
    def first(self):
        return self

    async def inner_text(self):
        return ""


class DummyLocator:
    def __init__(self, elements):
        self.elements = elements

    async def count(self):
        return len(self.elements)

    def nth(self, i):
        return self.elements[i]


class DummyFrame:
    def __init__(self, elements):
        self._elements = elements

    def locator(self, _selector):
        return DummyLocator(self._elements)


class DummyVerificationPage(DummyPage):
    pass


def test_external_contact_prefill():
    from src.application.common.company_website_agent import CompanyWebsiteAgent

    name = DummyElement(placeholder="Name")
    email = DummyElement(placeholder="Email*")
    phone = DummyElement(placeholder="Phone Number*")
    bare_contact = DummyElement(placeholder="Contact")
    frame = DummyFrame([name, email, phone, bare_contact])

    class Page:
        frames = [frame]
        def __init__(self):
            self._dummy = DummyPage()

    agent = CompanyWebsiteAgent(
        dry_run=True,
        profile_path=str(ROOT / "profile.json"),
        resume_path=str(ROOT / "resume" / "resume.pdf"),
    )
    agent.load_profile()

    # Bypass Playwright's actual page object for this focused deterministic test.
    agent.find_label = lambda element: asyncio.sleep(0, result="")
    agent.record = lambda *args, **kwargs: asyncio.sleep(0)

    async def run():
        count = await agent.fill_contact_fields_deterministically(Page())
        assert count == 4, count
        assert name.value == agent.get_value("full_name")
        assert email.value == "anuroop954@gmail.com"
        assert phone.value == "7032164500"
        assert bare_contact.value == "7032164500"

    asyncio.run(run())


def test_indeed_human_verification_auto_resumes():
    from platforms.indeed.indeed_agent import IndeedAgent

    agent = IndeedAgent()
    page = DummyVerificationPage()
    states = iter([True, True, False])

    async def fake_detect(_page):
        try:
            return next(states)
        except StopIteration:
            return False

    async def fake_wait_stable(_page):
        return True

    agent.detect_blocker = fake_detect
    agent.wait_stable = fake_wait_stable

    async def run():
        ok = await agent.pause_for_human_verification(page, "test")
        assert ok is True
        assert page.sleeps >= 1

    asyncio.run(run())


if __name__ == "__main__":
    test_external_contact_prefill()
    test_indeed_human_verification_auto_resumes()
    print("2/2 v25 focused tests passed")
