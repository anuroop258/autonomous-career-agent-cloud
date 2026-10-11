import asyncio
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from src.application.common.ai_form_engine import AIFormEngine

PROFILE_PATH = ROOT / "platforms" / "linkedin" / "profile.json"
PROFILE = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def _field(**overrides):
    base = {
        "label": "",
        "placeholder": "",
        "aria_label": "",
        "name": "",
        "field_id": "",
        "field_type": "text",
        "tag": "input",
        "role": "",
        "context": "",
        "options": [],
    }
    base.update(overrides)
    return base


def test_external_short_identity_location_labels_classify_to_safe_semantics():
    engine = AIFormEngine(profile=PROFILE)

    assert engine._classify(**_field(label="Address", name="address")) == "address"
    assert engine._classify(**_field(label="Place", name="place")) == "city"
    assert engine._classify(**_field(label="Location", name="location")) == "city"
    assert engine._classify(**_field(label="Contact", name="contact", field_type="tel")) == "phone"
    assert engine._classify(**_field(label="Contact", name="contact", field_type="text")) == "phone"


def test_profile_has_city_but_no_street_address():
    engine = AIFormEngine(profile=PROFILE)
    assert engine.get_profile_value("city") == "Hyderabad"
    assert engine.get_profile_value("address") in (None, "")


def test_reasoner_cannot_put_first_name_into_missing_address_or_place():
    engine = AIFormEngine(profile=PROFILE)

    class FakeReasoner:
        def reason(self, *args, **kwargs):
            return {"answer": "Anuroop", "kind": "text", "confidence": 1.0}

    engine._get_reasoner = lambda: FakeReasoner()

    async def run():
        for semantic, label in (("address", "Address"), ("city", "Place")):
            ok = await engine._reason_and_fill({
                "semantic": semantic,
                "label": label,
                "tag": "input",
                "type": "text",
                "locator": None,
            })
            assert ok is False

    asyncio.run(run())
