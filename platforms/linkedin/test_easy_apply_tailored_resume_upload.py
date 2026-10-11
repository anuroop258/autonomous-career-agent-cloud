import asyncio
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from linkedin_agent import LinkedInAgent


class FakeFileInput:
    def __init__(self):
        self.selected = []

    async def set_input_files(self, path):
        self.selected.append(path)

    async def evaluate(self, _script):
        return [{"name": Path(self.selected[-1]).name}] if self.selected else []


class FakeInputs:
    def __init__(self, item):
        self.item = item

    async def count(self):
        return 1

    def nth(self, _i):
        return self.item


class FakePage:
    def __init__(self, item):
        self.item = item

    def locator(self, _selector):
        return FakeInputs(self.item)


def test_linkedin_native_upload_prefers_job_specific_tailored_resume(tmp_path):
    tailored = tmp_path / "tailored.pdf"
    master = tmp_path / "master.pdf"
    tailored.write_bytes(b"tailored")
    master.write_bytes(b"master")

    agent = LinkedInAgent()
    agent.current_resume_path = str(tailored)
    agent.profile["resume"] = {"path": str(master)}

    file_input = FakeFileInput()
    ok = asyncio.run(agent._upload_linkedin_resume(FakePage(file_input)))

    assert ok is True
    assert file_input.selected == [str(tailored)]
