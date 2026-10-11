
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "platforms" / "indeed"))

from profile_reasoner import ProfileReasoner as RootReasoner
from platforms.indeed.profile_reasoner import ProfileReasoner as IndeedReasoner
from resume_tailer import verify_pdf


def test_reasoner_signature_and_identity():
    assert RootReasoner is IndeedReasoner
    import inspect
    assert "context" in inspect.signature(RootReasoner.reason).parameters


def test_pdf_fallback_when_pymupdf_unavailable(monkeypatch, tmp_path):
    pdf = tmp_path / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.7 fake")
    monkeypatch.setitem(sys.modules, "fitz", None)
    result = verify_pdf(pdf)
    assert result["verification_skipped"] is True
    assert result["verification_reason"] == "PyMuPDF unavailable"
    assert result["hyperlinks_checked"] is False


if __name__ == "__main__":
    test_reasoner_signature_and_identity()
    test_pdf_fallback_when_pymupdf_unavailable(type("M", (), {"setitem": lambda self,*a:None})(), Path("."))
    print("PASS: canonical reasoner + PDF fallback")
