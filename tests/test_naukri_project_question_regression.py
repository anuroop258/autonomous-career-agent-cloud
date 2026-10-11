import asyncio

import pytest
from playwright.async_api import async_playwright

from naukri_agent import NaukriAgent
from src.application.common.qa_engine import AnswerEngine
from src.application.common.question_router import QuestionIntentRouter


PROJECT_Q = "Could you briefly explain the AI projects or applications you have built?"


def test_project_question_routes_as_project_text_even_with_transcript_artifacts():
    route = QuestionIntentRouter.route(label=PROJECT_Q, options=["Yes", "Save"])
    assert route["intent"] == "project_text"

    answer, field, kind = AnswerEngine().answer(PROJECT_Q, ["Yes", "Save"])
    assert answer
    assert field == "projects"
    assert kind == "text"
    assert "AI-Powered Autonomous Job Application Agent" in answer
    assert len(answer) < 600


@pytest.mark.asyncio
async def test_naukri_visible_options_exclude_previous_answers_and_save():
    html = f"""
    <div role="dialog" style="width:700px;padding:20px">
      <div class="chat">
        <div class="question">Do you have hands-on experience with Claude and the Emergent platform?</div>
        <button class="answer-bubble">Yes</button>
        <div class="question">Do you have any experience working with AI/Generative AI technologies?</div>
        <button class="answer-bubble">Yes</button>
        <div class="question">{PROJECT_Q}</div>
        <textarea placeholder="Type message here..."></textarea>
        <button>Save</button>
      </div>
    </div>
    """
    agent = NaukriAgent.__new__(NaukriAgent)
    agent.answered = set()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        page = await browser.new_page()
        await page.set_content(html)
        q = await agent.current_question(page)
        assert q == PROJECT_Q
        options = await agent.visible_options(page, q)
        assert options == []
        await browser.close()


@pytest.mark.asyncio
async def test_naukri_fills_project_text_without_entering_or_using_search():
    html = f"""
    <div role="dialog" style="width:700px;padding:20px">
      <div class="chat">
        <div class="question">{PROJECT_Q}</div>
        <textarea placeholder="Type message here..."></textarea>
        <button>Save</button>
      </div>
      <input placeholder="Search jobs" />
    </div>
    """
    agent = NaukriAgent.__new__(NaukriAgent)
    agent.answered = set()
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, executable_path="/usr/bin/chromium")
        page = await browser.new_page()
        await page.set_content(html)
        answer, _, kind = AnswerEngine().answer(PROJECT_Q, [])
        assert kind == "text"
        ok = await agent.fill_answer_in_panel(page, answer, kind, question=PROJECT_Q, options=[])
        assert ok
        value = await page.locator("textarea").input_value()
        assert value == answer
        assert await page.locator("input[placeholder='Search jobs']").input_value() == ""
        await browser.close()
