import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from jd_matcher import JDMatcher

def main():
    matcher = JDMatcher(str(ROOT))
    cases = [
        ("Experience: 4-6 years of experience in Generative AI.", False),
        ("4 to 6 years experience required.", False),
        ("4–6 years of experience.", False),
        ("Minimum 4 years of relevant experience.", False),
        ("At least 4 years of hands-on experience.", False),
        ("5+ years of experience in GenAI.", False),
        ("3+ years of experience in LLM applications.", False),
        ("2+ years of experience in LLM applications.", False),
        ("3 years of experience in RAG.", False),
        ("1-3 years of experience.", False),
        ("2 years of experience.", False),
        ("0-1 years experience; fresher welcome.", True),
        ("0-2 years experience; freshers welcome.", True),
        ("0 to 3 years of experience.", True),
        ("0–3 years experience preferred.", True),
        ("Fresher / entry-level role with no experience required.", True),
        ("No experience required.", True),
        ("Experience: 0-3 years. Strong Python and GenAI skills.", True),
    ]
    for text, expected in cases:
        _, note, ok = matcher._experience_fit("", matcher._norm(text))
        assert ok is expected, f"{text!r}: expected {expected}, got {ok} ({note})"
    print("EXPERIENCE REGRESSION: PASS")

if __name__ == "__main__":
    main()
