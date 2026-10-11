from qa_engine import AnswerEngine

e = AnswerEngine()
checks = [
    ("What is your year of graduation?", [], "2026"),
    ("What is your CGPA?", [], "6.8"),
    ("Is your CGPA below 7?", ["Yes", "No"], "Yes"),
    ("Do you have 7 or more CGPA?", ["Yes", "No"], "No"),
    ("How many years of professional experience do you have?", [], "0"),
    ("What is your B.E./B.Tech percentage?", [], "68"),
    ("What is your 10th percentage?", [], "95"),
    ("Do you have internship experience?", ["Yes", "No"], "No"),
    ("Do you know prompt engineering?", ["Yes", "No"], "Yes"),
    ("Do you have experience with RAG?", ["Yes", "No"], "Yes"),
]
for q, opts, expected in checks:
    ans, field, kind = e.answer(q, opts)
    assert str(ans) == expected, (q, ans, expected)
print("QA regression: PASS")


# Application-state safety regression: DRY_RUN must never click final Submit.
import asyncio
import os
from indeed_agent import IndeedAgent

class FakePage:
    url = "https://in.indeed.com/viewjob?jk=test"
    def __init__(self):
        self.body = "Review your application\nSubmit your application"
    async def inner_text(self, **kwargs):
        return self.body
    async def is_closed(self):
        return False

class FakeAgent(IndeedAgent):
    def __init__(self):
        os.environ["DRY_RUN"] = "true"
        super().__init__()
        self.submit_called = False
    async def detect_blocker(self, page):
        return False
    async def get_job_text(self, page):
        return page.body
    async def submit(self, page):
        self.submit_called = True
        return True
    async def _upload_tailored_resume_on_indeed_review(self, page):
        self._indeed_resume_replaced = True
        return True

async def _safety_check():
    a = FakeAgent()
    result = await a.run_application(FakePage(), "https://in.indeed.com/viewjob?jk=test")
    assert result == "ready_to_submit", result
    assert a.submit_called is False, "DRY_RUN clicked final Submit"

asyncio.run(_safety_check())
print("DRY_RUN submit safety: PASS")
