import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def _ensure_playwright():
    """Install the project Playwright dependency on first run if it is missing."""
    try:
        import playwright  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    req = ROOT / "requirements.txt"
    print("PLAYWRIGHT: Python package not found.")
    print(f"Installing dependencies from: {req}")
    rc = subprocess.call(
        [sys.executable, "-m", "pip", "install", "-r", str(req)],
        cwd=str(ROOT),
    )
    if rc != 0:
        raise SystemExit(
            "Could not install Python dependencies. Run: py -m pip install -r requirements.txt"
        )

    try:
        import playwright  # noqa: F401
    except ModuleNotFoundError as exc:
        raise SystemExit(
            "Playwright is still unavailable after installation. "
            "Run: py -m pip install -r requirements.txt"
        ) from exc


def _ensure_project_python():
    bundled = ROOT / ".venv" / "Scripts" / "python.exe"
    if bundled.exists() and Path(sys.executable).resolve() != bundled.resolve():
        try:
            import playwright  # noqa: F401
        except Exception:
            env = os.environ.copy()
            return subprocess.call([str(bundled), str(Path(__file__).resolve()), *sys.argv[1:]], env=env, cwd=str(ROOT))
    return None

if hasattr(sys.stdout, "reconfigure"):
    # Do not let a legacy Windows console abort the launcher on Unicode output.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PLATFORMS = {
    "naukri": {
        "script": ROOT / "naukri_main.py",
        "cwd": ROOT,
        "port": 9222,
        "label": "Naukri",
    },
    "indeed": {
        "script": ROOT / "platforms" / "indeed" / "indeed_main.py",
        "cwd": ROOT / "platforms" / "indeed",
        "port": 9222,
        "label": "Indeed",
    },
    "linkedin": {
        "script": ROOT / "platforms" / "linkedin" / "linkedin_main.py",
        "cwd": ROOT / "platforms" / "linkedin",
        "port": 9232,
        "label": "LinkedIn",
    },
    "shine": {
        "script": ROOT / "platforms" / "shine" / "shine_main.py",
        "cwd": ROOT / "platforms" / "shine",
        "port": 9222,
        "label": "Shine",
    },
    "timesjobs": {
        "script": ROOT / "platforms" / "timesjobs" / "timesjobs_main.py",
        "cwd": ROOT / "platforms" / "timesjobs",
        "port": 9222,
        "label": "TimesJobs",
    },
    "glassdoor": {
        "script": ROOT / "platforms" / "glassdoor" / "glassdoor_main.py",
        "cwd": ROOT / "platforms" / "glassdoor",
        "port": 9222,
        "label": "Glassdoor",
    },
}

def choose_platform():
    print()
    print("======================================")
    print("  JOB APPLICATION AGENT")
    print("======================================")
    print("1. Naukri   (Chrome CDP 9222)")
    print("2. Indeed   (Chrome CDP 9222)")
    print("3. LinkedIn (Chrome CDP 9232)")
    print("4. Shine    (Chrome CDP 9222)")
    print("5. TimesJobs (Chrome CDP 9222)")
    print("6. Glassdoor (Chrome CDP 9222)")
    print()
    while True:
        choice = input("Select platform [1-3]: ").strip().lower()
        aliases = {"1": "naukri", "2": "indeed", "3": "linkedin", "4": "shine", "5": "timesjobs", "6": "glassdoor"}
        if choice in aliases:
            return aliases[choice]
        if choice in PLATFORMS:
            return choice
        print("Please enter 1-6 or a supported portal name.")

def main():
    _ensure_playwright()
    forwarded = _ensure_project_python()
    if forwarded is not None:
        return forwarded

    # Direct company-site mode intentionally bypasses portal search.
    # Usage:
    #   py main.py company-fill URL --platform linkedin --port 9232
    if len(sys.argv) >= 3 and sys.argv[1].lower() == "company-fill":
        from company_fill import main as company_fill_main
        sys.argv = [sys.argv[0], *sys.argv[2:]]
        return company_fill_main()
    parser = argparse.ArgumentParser(description="Unified job portal launcher")
    parser.add_argument("platform", nargs="?", choices=list(PLATFORMS))
    parser.add_argument("target", nargs="?", help="Optional search URL/target passed to the selected agent")
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to LinkedIn")
    args = parser.parse_args()

    platform = args.platform or choose_platform()
    cfg = PLATFORMS[platform]

    print(f"\nSELECTED: {cfg['label']}")
    print(f"CDP PORT: {cfg['port']}")
    print(f"ENTRY:    {cfg['script']}")
    print("\nIMPORTANT: Start the matching Chrome CDP session before running this command.")

    cmd = [sys.executable, str(cfg["script"])]
    if args.target:
        cmd.append(args.target)
    if args.dry_run and platform == "linkedin":
        cmd.append("--dry-run")

    env = os.environ.copy()
    env["JOB_AGENT_PLATFORM"] = platform
    env["JOB_AGENT_CDP_PORT"] = str(cfg["port"])
    return subprocess.call(cmd, cwd=str(cfg["cwd"]), env=env)

if __name__ == "__main__":
    raise SystemExit(main())
