import asyncio
from linkedin_agent import LinkedInAgent


class FakePage:
    def __init__(self):
        self.url = "https://www.linkedin.com/jobs/search/?keywords=GenAI+Engineer"
        self.goto_calls = []

    async def goto(self, url, **kwargs):
        self.goto_calls.append(url)
        self.url = url

    def is_closed(self):
        return False

    def locator(self, selector):
        return self

    async def inner_text(self, timeout=5000):
        return "No matching jobs found. Jobs you may be interested in"


class FakeContext:
    def __init__(self, page):
        self.pages = [page]

    async def new_page(self):
        raise AssertionError("A LinkedIn search controller should already exist for this regression.")


async def main():
    agent = LinkedInAgent()
    page = FakePage()
    context = FakeContext(page)
    calls = {"collect": 0, "next": 0, "process": 0}

    async def collect(_page):
        calls["collect"] += 1
        return []

    async def next_url(_page, current_url, page_number):
        calls["next"] += 1
        return current_url + "&start=25"

    async def process(_context, _url):
        calls["process"] += 1
        raise AssertionError("No job should be opened when the search page has zero jobs.")

    agent.collect_job_urls = collect
    agent.next_search_url = next_url
    agent.process_job = process

    await agent.run_with_context(context, page.url)

    assert calls["collect"] == 1
    assert calls["next"] == 0, "Zero-result page must stop before pagination is evaluated."
    assert calls["process"] == 0
    assert len(page.goto_calls) == 1
    print("LINKEDIN ZERO-RESULT PAGINATION REGRESSION: PASS")


if __name__ == "__main__":
    asyncio.run(main())
