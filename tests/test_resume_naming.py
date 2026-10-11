from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resume_integration import _clean_role_title


def test_indeed_role_title_is_human_readable():
    assert _clean_role_title(
        "Python Developer (GenAI) - Gurugram, Haryana - Indeed.com", "indeed"
    ) == "Python Developer (GenAI)"
