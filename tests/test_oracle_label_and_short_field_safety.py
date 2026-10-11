import asyncio
import json
import sys
from pathlib import Path

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

from src.application.common.adaptive_form_runtime import FormObserver
from src.application.common.ai_form_engine import AIFormEngine

PROFILE = json.loads(
    (ROOT / "platforms" / "linkedin" / "profile.json").read_text(encoding="utf-8")
)


ORACLE_SHADOW_HTML = """
<!doctype html>
<html><body>
<form>
  <oj-input-text id="current-location" label-hint="Current Location"></oj-input-text>
  <oj-input-text id="role" label-hint="Role"></oj-input-text>
  <oj-text-area id="message" label-hint="Why are you interested?"></oj-text-area>
</form>
<script>
class OracleInput extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const root = this.attachShadow({mode: 'open'});
    const input = document.createElement('input');
    input.type = 'text';
    input.name = this.id;
    root.appendChild(input);
  }
}
customElements.define('oj-input-text', OracleInput);

class OracleTextArea extends HTMLElement {
  connectedCallback() {
    if (this.shadowRoot) return;
    const root = this.attachShadow({mode: 'open'});
    root.appendChild(document.createElement('textarea'));
  }
}
customElements.define('oj-text-area', OracleTextArea);
</script>
</body></html>
"""


def test_oracle_label_hint_recovers_shadow_dom_labels_and_fills_profile_fields():
    from playwright.async_api import async_playwright

    async def run_case():
        async with async_playwright() as pw:
            browser = await _launch_chromium(pw)
            page = await browser.new_page()
            await page.set_content(ORACLE_SHADOW_HTML)

            engine = AIFormEngine(page=page, profile=PROFILE)
            fields = await engine.inspect_form()
            by_label = {field["label"]: field for field in fields}

            assert by_label["Current Location"]["semantic"] == "city"
            assert by_label["Role"]["semantic"] == "job_role"

            result = await engine.fill_safe_fields()

            location = page.locator("oj-input-text#current-location input")
            role = page.locator("oj-input-text#role input")
            assert await location.input_value() == "Hyderabad"
            assert await role.input_value() == PROFILE["candidate"]["current_designation"]
            assert result["fields_filled"] >= 2

            await browser.close()

    asyncio.run(run_case())


def test_single_line_unknown_field_rejects_narrative_reasoner_answer():
    engine = AIFormEngine(profile=PROFILE)

    class FakeReasoner:
        def reason(self, *args, **kwargs):
            return {
                "answer": "I am Anuroop Kudire, a 2026 graduate with experience in Python, AI/ML, Generative AI, RAG, and automation projects. "
                          "I enjoy building intelligent applications and solving practical problems.",
                "confidence": 0.99,
            }

    engine._get_reasoner = lambda: FakeReasoner()

    async def run_case():
        return await engine._reason_and_fill({
            "semantic": "unknown",
            "label": "Role",
            "tag": "input",
            "type": "text",
            "role": "textbox",
            "locator": None,
            "options": [],
        })

    assert asyncio.run(run_case()) is False


def test_generic_textarea_reasoner_path_remains_enabled():
    from playwright.async_api import async_playwright

    class FakeReasoner:
        def reason(self, question, *args, **kwargs):
            return {"answer": f"Generated response for {question}", "confidence": 0.99}

    async def run_case():
        async with async_playwright() as pw:
            browser = await _launch_chromium(pw)
            page = await browser.new_page()
            await page.set_content(
                '<label for="message">Why are you interested?</label><textarea id="message"></textarea>'
            )
            engine = AIFormEngine(page=page, profile=PROFILE)
            engine._get_reasoner = lambda: FakeReasoner()
            fields = await engine.inspect_form()
            field = next(x for x in fields if x["id"] == "message")
            ok = await engine._reason_and_fill(field)
            value = await page.locator("#message").input_value()
            await browser.close()
            return ok, value

    ok, value = asyncio.run(run_case())
    assert ok is True
    assert value.startswith("Generated response for")

