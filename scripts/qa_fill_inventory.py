#!/usr/bin/env python3
"""
Non-destructive inventory for QA/question-answering/form-filling debugging.

It searches the repository for likely profile, QA, routing, and Playwright code
and writes a compact report. It does NOT modify application files.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import re
import json

PATTERNS = {
    "profile": re.compile(r"profile(reasoner)?|online_profiles|linkedin|github|postal|notice|graduat|cgpa|experience", re.I),
    "qa": re.compile(r"\b(qa|question|answer|reason|route|routing|unknown_question|normalize)\b", re.I),
    "fill": re.compile(r"\b(fill|locator|input|select|checkbox|radio|label|placeholder|aria-label|verification|verify)\b", re.I),
    "llm": re.compile(r"\b(gemini|ollama|openai|llm|429|404)\b", re.I),
    "playwright": re.compile(r"\b(playwright|page\.|locator\(|get_by_|expect\()\b", re.I),
}

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", ".mypy_cache", ".pytest_cache"}

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=".")
    args = ap.parse_args()

    root = Path(args.project).resolve()
    report = {"project": str(root), "files": {}, "summary": {}}

    counts = {k: 0 for k in PATTERNS}

    for p in sorted(root.rglob("*")):
        if not p.is_file() or any(part in SKIP_DIRS for part in p.parts):
            continue
        if p.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".json", ".md", ".ps1"}:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue

        hits = {}
        for name, rx in PATTERNS.items():
            n = len(rx.findall(text))
            if n:
                hits[name] = n
                counts[name] += n

        if hits:
            rel = str(p.relative_to(root))
            report["files"][rel] = hits

    report["summary"] = counts
    out = root / "debug-evidence" / "qa_fill_inventory.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"QA/fill inventory written to: {out}")
    print(json.dumps(counts, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
