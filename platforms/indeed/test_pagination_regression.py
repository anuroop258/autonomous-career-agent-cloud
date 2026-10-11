import asyncio
import json
from pathlib import Path
from indeed_agent import IndeedAgent

async def main():
    agent = IndeedAgent()
    base = "https://in.indeed.com/jobs?q=GenAI+Engineer&l=Hyderabad%2C+Telangana"
    p1 = await agent._next_search_page_url(None, base, 1)
    p2 = await agent._next_search_page_url(None, p1, 2)
    p3 = await agent._next_search_page_url(None, p2, 3)
    p4 = await agent._next_search_page_url(None, p3, 4)
    p5 = await agent._next_search_page_url(None, p4, 5)
    assert "start=10" in p1 and "start=20" in p2 and "start=30" in p3 and "start=40" in p4
    assert p5 is None
    assert len({p1,p2,p3,p4}) == 4
    print("PAGINATION REGRESSION: PASS")

if __name__ == "__main__":
    asyncio.run(main())
