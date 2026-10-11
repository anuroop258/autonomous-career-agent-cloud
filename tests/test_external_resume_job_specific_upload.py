from pathlib import Path
import json

from src.application.common.company_website_agent import CompanyWebsiteAgent


def _profile(path: Path):
    path.write_text(json.dumps({
        "resume": {"path": str(path.parent / "master_resume.pdf")}
    }), encoding="utf-8")


def test_explicit_job_resume_path_wins_over_profile_master(tmp_path):
    profile = tmp_path / "profile.json"
    master = tmp_path / "master_resume.pdf"
    tailored = tmp_path / "resume_versions" / "company" / "role" / "job-abc123" / "resume.pdf"
    tailored.parent.mkdir(parents=True)
    master.write_bytes(b"master")
    tailored.write_bytes(b"tailored")
    _profile(profile)

    agent = CompanyWebsiteAgent(profile_path=str(profile), resume_path=str(tailored))
    assert agent.get_resume_path() == str(tailored)


def test_external_upload_copy_is_job_specific(tmp_path):
    profile = tmp_path / "profile.json"
    tailored = tmp_path / "resume_versions" / "indeed" / "Company" / "Role" / "job-abc123" / "resume.pdf"
    tailored.parent.mkdir(parents=True)
    tailored.write_bytes(b"unique tailored resume content")
    _profile(profile)

    agent = CompanyWebsiteAgent(profile_path=str(profile), resume_path=str(tailored))
    target = Path(agent._prepare_external_resume_upload_copy(str(tailored)))

    assert target.exists()
    assert target.name.startswith("Anuroop_Kudire_")
    assert "job-abc123" in target.name
    assert target.name != "resume.pdf"
    assert target.read_bytes() == tailored.read_bytes()
