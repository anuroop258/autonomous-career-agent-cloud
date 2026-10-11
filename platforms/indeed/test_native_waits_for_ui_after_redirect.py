import asyncio
import importlib
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "platforms" / "indeed"))

# The historical V28 storage module may not expose the helper expected by the
# current Indeed agent. Keep this test focused on the native wait helper itself.
storage = importlib.import_module("storage")
if not hasattr(storage, "canonical_job_key"):
    storage.canonical_job_key = lambda *args, **kwargs: ""

from platforms.indeed.indeed_agent import IndeedAgent


class _FakeLocator:
    async def count(self):
        return 0


class _FakePage:
    def __init__(self, url, ready_after=0.0, frames=None):
        self.url = url
        self._started = time.monotonic()
        self._ready_after = ready_after
        self._closed = False
        self.main_frame = self
        self.frames = list(frames or [])


    def is_closed(self):
        return self._closed

    async def wait_for_load_state(self, *args, **kwargs):
        return None

    async def wait_for_timeout(self, ms):
        await asyncio.sleep(ms / 1000.0)

    def ready(self):
        return (time.monotonic() - self._started) >= self._ready_after

    def locator(self, selector):
        return _FakeLocator()


class _FakeFrame(_FakePage):
    pass


class _FakeContext:
    def __init__(self, pages):
        self.pages = pages


class _WaitProbeAgent(IndeedAgent):
    async def detect_blocker(self, page):
        return False

    async def get_job_text(self, page):
        return "Review your application" if page.ready() else "Loading native application"

    async def current_question(self, page):
        return None

    async def _control_label(self, el):
        return ""

    async def _wait_for_native_application_target(self, context, source_page, pages_before, source_url, timeout_ms=30000):
        return await super()._wait_for_native_application_target(
            context, source_page, pages_before, source_url, timeout_ms=timeout_ms
        )


def test_smartapply_target_url_alone_does_not_end_wait():
    async def run():
        source = _FakePage("https://in.indeed.com/viewjob?jk=test", ready_after=999.0)
        candidate = _FakePage(
            "https://smartapply.indeed.com/beta/indeedapply/applybyapplyablejobid?indeedApplyableJobId=test",
            ready_after=1.8,
        )
        context = _FakeContext([source, candidate])
        agent = _WaitProbeAgent()

        started = time.monotonic()
        result = await agent._wait_for_native_application_target(
            context,
            source,
            {source},
            source.url,
            timeout_ms=7000,
        )
        elapsed = time.monotonic() - started

        assert result is candidate
        assert elapsed >= 1.5, elapsed

    asyncio.run(run())


def test_same_tab_smartapply_target_waits_for_ui():
    async def run():
        source = _FakePage(
            "https://smartapply.indeed.com/beta/indeedapply/form/review-module?test=1",
            ready_after=1.8,
        )
        context = _FakeContext([source])
        agent = _WaitProbeAgent()

        started = time.monotonic()
        result = await agent._wait_for_native_application_target(
            context,
            source,
            {source},
            "https://in.indeed.com/viewjob?jk=test",
            timeout_ms=7000,
        )
        elapsed = time.monotonic() - started

        assert result is source
        assert elapsed >= 1.5, elapsed

    asyncio.run(run())


def test_new_tab_iframe_application_ui_counts_as_ready():
    async def run():
        source = _FakePage("https://in.indeed.com/viewjob?jk=test", ready_after=999.0)
        frame = _FakeFrame("https://smartapply.indeed.com/frame", ready_after=0.2)
        candidate = _FakePage(
            "https://smartapply.indeed.com/beta/indeedapply/applybyapplyablejobid?indeedApplyableJobId=test",
            ready_after=999.0,
            frames=[frame],
        )
        context = _FakeContext([source, candidate])
        agent = _WaitProbeAgent()

        started = time.monotonic()
        result = await agent._wait_for_native_application_target(
            context, source, {source}, source.url, timeout_ms=4000
        )
        elapsed = time.monotonic() - started

        assert result is candidate
        assert elapsed >= 0.15, elapsed

    asyncio.run(run())
