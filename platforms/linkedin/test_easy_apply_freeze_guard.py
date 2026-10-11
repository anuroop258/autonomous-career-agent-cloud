from pathlib import Path
import ast
import hashlib
import json

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "platforms" / "linkedin" / "linkedin_agent.py"
MANIFEST = ROOT / "platforms" / "linkedin" / "EASY_APPLY_FREEZE_MANIFEST.json"

def _function_blocks():
    src = SRC.read_text(encoding="utf-8")
    lines = src.splitlines(keepends=True)
    tree = ast.parse(src)
    wanted = set(json.loads(MANIFEST.read_text(encoding="utf-8"))["functions"])
    out = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in wanted:
            block = "".join(lines[node.lineno - 1:node.end_lineno])
            out[node.name] = hashlib.sha256(block.encode()).hexdigest()
    return out

def test_frozen_easy_apply_core_has_not_changed():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    current = _function_blocks()
    expected = {name: data["sha256"] for name, data in manifest["functions"].items()}
    assert current == expected, (
        "Frozen Easy Apply CTA baseline changed. Update the freeze manifest only after "
        "deliberately reviewing and approving the CTA behavior change. "
        f"Expected={expected} Current={current}"
    )

def test_frozen_config_and_tab_contract():
    cfg = json.loads((ROOT / "platforms" / "linkedin" / "linkedin_config.json").read_text(encoding="utf-8"))
    assert cfg["native_apply_types"] == ["easy_apply_single_step", "easy_apply_multi_step"]
    assert cfg["leave_native_apply_tab_open"] is True
    assert cfg["leave_native_apply_tab_open_on_unresolved"] is True
