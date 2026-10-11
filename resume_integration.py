from __future__ import annotations
import hashlib, json, re, unicodedata
from pathlib import Path
from resume_tailer import ATSAuthenticResumeTailor, compile_latex, verify_pdf

ROOT = Path(__file__).resolve().parent


def _sha256_file(path: Path) -> str:
    import hashlib as _hashlib
    h = _hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_name(value: str | None, fallback: str) -> str:
    raw = unicodedata.normalize("NFKC", str(value or "")).strip()
    raw = re.sub(r'[\x00-\x1f<>:"/\\|?*]', ' ', raw)
    raw = re.sub(r"\s+", " ", raw).strip(" .")
    if not raw:
        raw = fallback
    if raw.upper().split(".")[0] in {
        "CON", "PRN", "AUX", "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }:
        raw = f"_{raw}"
    return raw[:100].rstrip(" .") or fallback


def _safe_company_folder(company: str | None) -> str:
    return _safe_name(company, "Unknown_Company")


def _clean_role_title(title: str | None, platform: str) -> str:
    raw = unicodedata.normalize("NFKC", str(title or "")).strip()
    if platform.lower() == "indeed":
        # Indeed document titles often end with the location and/or "Indeed.com".
        raw = re.sub(r"\s+-\s+Indeed\.com\s*$", "", raw, flags=re.I)
        raw = re.sub(r"\s+\|\s+Indeed\.com\s*$", "", raw, flags=re.I)
        parts = [p.strip() for p in re.split(r"\s+-\s+", raw) if p.strip()]
        if len(parts) >= 2 and re.search(r"\b(India|Haryana|Gujarat|Maharashtra|Telangana|Karnataka|Tamil Nadu|Delhi|Mumbai|Pune|Gurugram|Gurgaon|Hyderabad|Ahmedabad|Bengaluru|Bangalore|Chennai|Noida|Remote)\b", parts[-1], re.I):
            raw = " - ".join(parts[:-1]).strip()
    if platform.lower() == "linkedin":
        raw = re.sub(r"\s*\|\s*LinkedIn\s*$", "", raw, flags=re.I)
    return _safe_name(raw, "Unknown_Role")


# Generated resume paths intentionally use bounded folder names. The full
# company/role strings remain in job_metadata.json, while the filesystem path
# carries only a short human hint plus a collision-resistant hash. This keeps
# newly generated paths portable even when the checkout itself is nested.
MAX_GENERATED_RESUME_RELATIVE_PATH = 110


def _resume_output_dir(root: Path, platform: str, company: str | None, role: str | None, job_key: str) -> Path:
    company_folder = _safe_company_folder(company)
    role_folder = _clean_role_title(role, platform)
    company_key = hashlib.sha256(company_folder.encode("utf-8")).hexdigest()[:6]
    role_key = hashlib.sha256(role_folder.encode("utf-8")).hexdigest()[:6]
    compact_company = _safe_name(company_folder, "Company")[:16].rstrip(" .") or "Company"
    compact_role = _safe_name(role_folder, "Role")[:20].rstrip(" .") or "Role"
    output = (root / "resume_versions" / platform /
              f"{compact_company}-{company_key}" /
              f"{compact_role}-{role_key}" / f"j-{job_key}")
    relative = Path("resume_versions") / platform / output.relative_to(root / "resume_versions" / platform)
    if len(str(relative / "resume.pdf")) > MAX_GENERATED_RESUME_RELATIVE_PATH:
        raise RuntimeError("generated resume path exceeded bounded relative path budget")
    return output


def build_tailored_resume(*, profile_path: str | Path, title: str, jd_text: str, platform: str, job_url: str, company: str | None = None) -> str | None:
    try:
        profile = json.loads(Path(profile_path).read_text(encoding="utf-8"))
        master = ROOT / "resume" / "master_resume.tex"
        if not master.exists():
            return None
        key = hashlib.sha256(f"{platform}|{job_url}".encode("utf-8")).hexdigest()[:8]
        company_folder = _safe_company_folder(company)
        role_folder = _clean_role_title(title, platform)
        output = _resume_output_dir(ROOT, platform, company, title, key)
        print(f"  RESUME PATH: bounded storage path; using {output}")
        output.mkdir(parents=True, exist_ok=True)
        pdf_path = output / "resume.pdf"
        metadata_path = output / "job_metadata.json"
        jd_hash = hashlib.sha256((jd_text or "").encode("utf-8")).hexdigest()
        master_hash = _sha256_file(master)
        profile_hash = hashlib.sha256(Path(profile_path).read_bytes()).hexdigest()
        if pdf_path.exists() and metadata_path.exists():
            try:
                cached_meta = json.loads(metadata_path.read_text(encoding="utf-8"))
            except Exception:
                cached_meta = {}
            if (cached_meta.get("jd_sha256") == jd_hash and
                cached_meta.get("master_sha256") == master_hash and
                cached_meta.get("profile_sha256") == profile_hash):
                print(f"  RESUME CACHE HIT: {pdf_path}")
                return str(pdf_path)

        tailored = ATSAuthenticResumeTailor(profile, master).tailor(jd_text, title)
        (output / "resume.tex").write_text(tailored.latex, encoding="utf-8")
        pdf = compile_latex(tailored.latex, output, "resume")
        verification = verify_pdf(pdf)
        tailored.report["verification"] = verification
        # Keep runtime folders clean: users need the source .tex, final PDF,
        # report and metadata, not compiler scratch files.
        for scratch in output.glob("resume.*"):
            if scratch.suffix.lower() in {".aux", ".log", ".out", ".fls", ".fdb_latexmk"}:
                try:
                    scratch.unlink()
                except OSError:
                    pass

        report = {
            "method": "ATS keyword extraction + exact/near match + fact-preserving safe additions",
            "company": company_folder,
            "role": role_folder,
            "platform": platform,
            "job_url": job_url,
            "job_key": key,
            "source_of_truth": str(master.relative_to(ROOT)),
            **tailored.report,
        }
        report_path = output / "tailoring_report.json"
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

        # Save project-relative paths so exported project archives remain portable.
        # The backend resolves relative PDF paths against the project ROOT.
        metadata = {
            "company": company_folder,
            "role": role_folder,
            "platform": platform,
            "job_url": job_url,
            "job_key": key,
            "pdf": str(pdf.relative_to(ROOT)),
            "tailoring_report": str(report_path.relative_to(ROOT)),
            "matched_skills": tailored.matched_skills,
            "added_keywords": tailored.report.get("added_keywords", []),
            "keyword_inventory_count": tailored.report.get("keyword_inventory_count", 0),
            "phrase_inventory_count": tailored.report.get("phrase_inventory_count", 0),
            "authenticity_flags": len(tailored.report.get("authenticity_flags", [])),
            "bullet_word_counts": tailored.report.get("bullet_word_counts", []),
            "jd_sha256": jd_hash,
            "master_sha256": master_hash,
            "profile_sha256": profile_hash,
        }
        (output / "job_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        print(f"  RESUME COMPANY: {company_folder}")
        print(f"  RESUME ROLE: {role_folder}")
        print(f"  RESUME TAILORED: {pdf}")
        print("  RESUME MATCHED SKILLS:", ", ".join(tailored.matched_skills) if tailored.matched_skills else "none")
        print(
            f"  ATS TAILORING: keywords={tailored.report.get('keyword_inventory_count', 0)} "
            f"phrases={tailored.report.get('phrase_inventory_count', 0)} "
            f"added={len(tailored.report.get('added_keywords', []))} "
            f"unsupported={len(tailored.report.get('unsupported_keywords', []))} "
            f"auth_flags={len(tailored.report.get('authenticity_flags', []))}"
        )
        return str(pdf)
    except Exception as exc:
        print(f"  RESUME ROUTING WARNING: {type(exc).__name__}: {exc}")
        return None
