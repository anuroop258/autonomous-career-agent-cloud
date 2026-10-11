# Unified 3-platform runner

One codebase/package, with isolated platform implementations and a single `main.py` router.

## Interactive selection

```powershell
cd "C:\Users\Anuroop\Downloads\job_agents_UNIFIED_3_PLATFORM"
python main.py
```

Choose:

```text
1. Naukri   (9222)
2. Indeed   (9222)
3. LinkedIn (9232)
```

## Direct commands

```powershell
python main.py naukri
python main.py indeed
python main.py linkedin
```

Optional target/search URL:

```powershell
python main.py naukri "https://www.naukri.com/..."
python main.py indeed "https://in.indeed.com/..."
python main.py linkedin "https://www.linkedin.com/jobs/search/..."
```

LinkedIn dry run:

```powershell
python main.py linkedin --dry-run
```

## Chrome sessions

Naukri / Indeed (9222):

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\NaukriAgentRealChrome" --profile-directory="Default"
```

LinkedIn (9232):

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9232 --user-data-dir="$env:LOCALAPPDATA\LinkedInAgentRealChrome" --profile-directory="Default"
```

Do not run Naukri and Indeed simultaneously against the same 9222 Chrome session. Select one
platform for 9222, or give Indeed its own isolated browser/profile if simultaneous execution
is later required.

The Naukri external/company-site Apply rule remains enforced: matching jobs whose Apply CTA
leads to a company/external site are clicked only when the Apply CTA is validated, then passed to the canonical company-site form engine.
