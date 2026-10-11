from pathlib import Path


def test_indeed_no_questions_preserves_live_native_state_and_avoids_legacy_disposal():
    source = (Path(__file__).resolve().parent / "platforms" / "indeed" / "indeed_agent.py").read_text(encoding="utf-8")
    assert 'return "no_form_field"' not in source
    assert '"form_discovery_failed"' in source
    assert "HARD NATIVE-APPLY SAFETY RULE" in source
    assert "if application_opened:" in source
    assert 'status in application_states_to_keep_open' in source
    assert '"submit_not_found"' in source
    assert '"submission_unconfirmed"' in source
