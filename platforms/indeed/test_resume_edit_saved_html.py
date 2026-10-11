import re
from pathlib import Path

HTML = Path(r"/mnt/data/Review the contents of this job application ｜ Indeed (9_25_2026 9：26：54 PM).html")

def test_saved_review_html_exposes_resume_edit_button():
    text = HTML.read_text(encoding="utf-8", errors="ignore")
    section = re.search(r'<section\s+data-testid=resumeSection\b[\s\S]*?</section>', text)
    assert section, "resumeSection not found"
    block = section.group(0)
    assert re.search(r'<button[^>]+aria-label=&quot;Edit\s+resume&quot;[^>]*>Edit</button>', block)
