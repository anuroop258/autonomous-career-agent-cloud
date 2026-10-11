
import asyncio
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


async def _launch_chromium(pw):
    """Use the environment's installed Playwright browser across OSes."""
    kwargs = {"headless": True}
    system_chromium = Path("/usr/bin/chromium")
    if system_chromium.exists():
        kwargs["executable_path"] = str(system_chromium)
        kwargs["args"] = ["--no-sandbox"]
    return await pw.chromium.launch(**kwargs)


def test_common_company_agent_has_custom_qa_and_range_matching():
    text = (ROOT / "src/application/common/company_website_agent.py").read_text(encoding="utf-8")
    assert "def _custom_answer" in text
    assert "find_custom_answer" in text
    assert "Numeric/range experience matching" in text
    assert "–|—|−|to" in text


def test_ai_form_engine_extracts_custom_answer_dict():
    text = (ROOT / "src/application/common/ai_form_engine.py").read_text(encoding="utf-8")
    assert "custom.get(\"answer\") if custom else None" in text
    assert "def _custom_answer" in text


def test_custom_qa_phrase_containment():
    text = (ROOT / "custom_qa_store.py").read_text(encoding="utf-8")
    assert "stored in qn or qn in stored" in text


def test_direct_company_dispatch_is_present():
    text = (ROOT / "main.py").read_text(encoding="utf-8")
    assert 'sys.argv[1].lower() == "company-fill"' in text


def test_direct_company_fill_module_exists():
    text = (ROOT / "company_fill.py").read_text(encoding="utf-8")
    assert "connect_over_cdp" in text
    assert "CompanyWebsiteAgent" in text


def test_common_agent_selects_zero_into_unicode_range():
    import sys
    import asyncio

    from src.application.common.company_website_agent import CompanyWebsiteAgent

    class Options:
        async def evaluate_all(self, _js):
            return [
                {"value": "", "text": "Select", "disabled": False},
                {"value": "0-2", "text": "0–2 years", "disabled": False},
                {"value": "3-5", "text": "3–5 years", "disabled": False},
            ]

    class FakeElement:
        def __init__(self):
            self.selected = ""

        def locator(self, selector):
            return Options()

        async def input_value(self):
            return self.selected

        async def select_option(self, value=None, label=None, timeout=None):
            self.selected = value if value is not None else label

        @property
        def page(self):
            return self

        async def wait_for_timeout(self, _ms):
            return None

    async def run_case():
        agent = CompanyWebsiteAgent()
        agent.record = lambda *a, **kw: asyncio.sleep(0)
        field = {
            "element": FakeElement(),
            "tag": "select",
            "type": "",
            "name": "experience_level",
            "id": "career-experience_level",
            "label": "Relevant AI experience*",
            "placeholder": "",
        }
        ok = await agent.fill_select(field, "experience", 0)
        return ok, field["element"].selected

    ok, selected = asyncio.run(run_case())
    assert ok
    assert selected == "0-2"


def test_custom_qa_store_matches_saved_label_and_long_helper_text(tmp_path, monkeypatch):
    import importlib
    import custom_qa_store as store

    db = tmp_path / "qa.db"
    monkeypatch.setattr(store, "DB", db)
    store = importlib.reload(store)
    store.save_custom_qa("Experience and projects", "PROJECT ANSWER")
    assert store.find_custom_answer("Experience and projects")["answer"] == "PROJECT ANSWER"
    assert store.find_custom_answer(
        "Tell us about your experience and projects, including roles, internships, and work you are proud of"
    )["answer"] == "PROJECT ANSWER"



def test_company_classifier_prioritizes_visible_name_label_over_bad_email_type():
    from src.application.common.company_website_agent import CompanyWebsiteAgent
    agent = CompanyWebsiteAgent()
    field = {
        "tag": "input", "type": "email", "name": "full_name",
        "id": "career-full_name", "label": "Full name*",
        "placeholder": "", "aria_label": "", "context": "",
    }
    assert agent.classify(field) == "full_name"


def test_company_classifier_ignores_honeypot():
    from src.application.common.company_website_agent import CompanyWebsiteAgent
    agent = CompanyWebsiteAgent()
    field = {
        "tag": "input", "type": "email", "name": "website",
        "id": "career-website", "label": "Leave this field empty",
        "placeholder": "", "aria_label": "", "context": "",
    }
    assert agent.classify(field) == "honeypot"


def test_company_classifier_does_not_turn_open_ended_experience_into_zero_years():
    from src.application.common.company_website_agent import CompanyWebsiteAgent
    agent = CompanyWebsiteAgent()
    field = {
        "tag": "textarea", "type": "", "name": "experience",
        "id": "career-experience", "label": "Experience and projects",
        "placeholder": "", "aria_label": "", "context": "",
    }
    assert agent.classify(field) == "unknown"


def test_external_form_generic_narrative_questions_still_generate_and_fill_answers():
    from playwright.async_api import async_playwright
    from src.application.common.ai_form_engine import AIFormEngine

    class FakeReasoner:
        def reason(self, question, options, context=None):
            return {
                "answer": f"GENERATED ANSWER: {question}",
                "confidence": 0.95,
            }

    async def run_case():
        async with async_playwright() as pw:
            browser = await _launch_chromium(pw)
            page = await browser.new_page()
            await page.set_content("""
                <form>
                    <label for="message">Message</label>
                    <textarea id="message"></textarea>
                    <label for="experience">Relevant Experience</label>
                    <textarea id="experience"></textarea>
                    <button type="button">Next</button>
                    <button type="button">Cancel</button>
                </form>
            """)
            engine = AIFormEngine(page=page, profile={})
            engine.reasoner = FakeReasoner()
            fields = await engine.inspect_form()
            result = await engine.fill_form_safely()
            values = {
                "message": await page.locator("#message").input_value(),
                "experience": await page.locator("#experience").input_value(),
            }
            buttons = [f for f in fields if f.get("tag") == "button"]
            await browser.close()
            return result, values, buttons

    result, values, buttons = asyncio.run(run_case())
    assert result["fields_filled"] == 2
    assert values["message"].startswith("GENERATED ANSWER:")
    assert values["experience"].startswith("GENERATED ANSWER:")
    assert buttons == []


def test_oracle_terms_acceptance_allows_next_progression():
    from playwright.async_api import async_playwright
    from src.application.common.company_website_agent import CompanyWebsiteAgent

    async def run_case():
        async with async_playwright() as pw:
            browser = await _launch_chromium(pw)
            page = await browser.new_page()
            await page.set_content("""
                <div id="step1">
                    <input required type="checkbox"
                           id="legal-disclaimer-checkbox"
                           style="position:absolute;left:-10000px"
                           aria-labelledby="legal-disclaimer-checkbox-label">
                    <label id="legal-disclaimer-checkbox-label"
                           for="legal-disclaimer-checkbox">
                        I agree with the terms and conditions
                    </label>
                    <button id="next" type="button">Next</button>
                </div>
                <div id="step2" hidden>Second step reached</div>
                <script>
                    document.querySelector('#next').addEventListener('click', () => {
                        const box = document.querySelector('#legal-disclaimer-checkbox');
                        if (!box.checked) return;
                        document.querySelector('#step1').hidden = true;
                        document.querySelector('#step2').hidden = false;
                    });
                </script>
            """)
            agent = CompanyWebsiteAgent()
            agent.record = lambda *args, **kwargs: asyncio.sleep(0)
            accepted = await agent.accept_terms(page)
            await page.locator("#next").click()
            progressed = await page.locator("#step2").is_visible()
            await browser.close()
            return accepted, progressed

    accepted, progressed = asyncio.run(run_case())
    assert accepted is True
    assert progressed is True


def test_oracle_hidden_terms_checkbox_uses_aria_labelledby_control():
    from playwright.async_api import async_playwright
    from src.application.common.company_website_agent import CompanyWebsiteAgent

    async def run_case():
        async with async_playwright() as pw:
            browser = await _launch_chromium(pw)
            page = await browser.new_page()
            await page.set_content("""
                <input required type="checkbox"
                       id="legal-disclaimer-checkbox"
                       style="position:absolute;left:-10000px"
                       aria-labelledby="legal-disclaimer-checkbox-label">
                <label id="legal-disclaimer-checkbox-label"
                       for="legal-disclaimer-checkbox">
                    I agree with the terms and conditions
                </label>
            """)
            agent = CompanyWebsiteAgent()
            agent.record = lambda *args, **kwargs: asyncio.sleep(0)
            accepted = await agent.accept_terms(page)
            checked = await page.locator("#legal-disclaimer-checkbox").is_checked()
            await browser.close()
            return accepted, checked

    accepted, checked = asyncio.run(run_case())
    assert accepted is True
    assert checked is True
