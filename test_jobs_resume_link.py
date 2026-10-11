from pathlib import Path

ROOT = Path(__file__).resolve().parent
JOBS = (ROOT / 'webapp' / 'frontend' / 'src' / 'pages' / 'Jobs.tsx').read_text(encoding='utf-8')
CLIENT = (ROOT / 'webapp' / 'frontend' / 'src' / 'api' / 'client.ts').read_text(encoding='utf-8')


def test_jobs_resume_link_uses_stored_pdf_flag_and_exact_job_ref():
    assert 'j.resume_pdf_available' in JOBS
    assert 'api.resumePdfUrl(j.job_ref || `${j.source}:${j.id}`)' in JOBS
    assert 'Open Resume' in JOBS


def test_job_type_exposes_resume_pdf_available():
    assert 'resume_pdf_available?: boolean' in CLIENT


def test_jobs_shows_generate_resume_for_truthy_eligible_values():
    assert 'Number(j.eligible) === 1' in JOBS
    assert 'Generate Resume' in JOBS


def test_backend_resume_lookup_supports_company_role_identity_fallback():
    backend = (ROOT / 'webapp' / 'backend' / 'main.py').read_text(encoding='utf-8')
    assert 'company: str | None = None, role: str | None = None' in backend
    assert 'same_identity = bool(' in backend
    assert 'meta_role = _normalize_resume_role' in backend
    assert 'company=company,' in backend and 'role=title,' in backend


def test_resume_role_normalization_matches_indeed_location_suffixes():
    import sys
    sys.path.insert(0, str(ROOT))
    from webapp.backend.main import _normalize_resume_role

    assert _normalize_resume_role("Lead AI Engineer - Hyderabad, Telangana - Indeed.com", "indeed") == "lead ai engineer"
    assert _normalize_resume_role("Lead AI Engineer", "indeed") == "lead ai engineer"
    assert _normalize_resume_role("Lead AI Engineer - Remote - Indeed.com", "indeed") == "lead ai engineer"


def test_backend_resume_lookup_finds_saved_pdf_when_indeed_role_has_location_suffix(tmp_path, monkeypatch):
    import json
    import webapp.backend.main as backend_mod

    resume_dir = tmp_path / "resume_versions" / "indeed" / "Acme" / "Lead AI Engineer" / "job-deadbeef"
    resume_dir.mkdir(parents=True)
    pdf = resume_dir / "resume.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    (resume_dir / "job_metadata.json").write_text(json.dumps({
        "company": "Acme",
        "role": "Lead AI Engineer",
        "platform": "indeed",
        "job_url": "https://www.indeed.com/viewjob?jk=deadbeef",
        "job_key": "deadbeef",
        "pdf": str(pdf),
    }), encoding="utf-8")

    monkeypatch.setattr(backend_mod, "ROOT", tmp_path)
    found = backend_mod._resume_pdf_path_for_url(
        "https://www.indeed.com/viewjob?jk=some-other-key",
        platform="indeed",
        job_key="some-other-key",
        company="Acme",
        role="Lead AI Engineer - Hyderabad, Telangana - Indeed.com",
    )
    assert found == pdf.resolve()
