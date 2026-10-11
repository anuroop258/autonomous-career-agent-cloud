# LinkedIn Agent — Exact Naukri Flow

This package adds a LinkedIn adapter while preserving the Naukri architecture:

`discover → current-run dedup → OPEN EVERY UNIQUE JOB → LIVE APPLIED CHECK → blocker check → live JD → JD/experience/AI gate → route detection → Easy Apply or shared CompanyWebsiteAgent → profile-grounded filling → verification → submission verification → record → next job → next page`

## Runtime

The agent attaches ONLY to an already-running real Google Chrome through:

`http://127.0.0.1:9222`

It does not launch Chromium/Chrome for Testing itself.

## Safety default

`LINKEDIN_DRY_RUN=true` by default. In dry-run mode, final LinkedIn submission is blocked, while intermediate form work can be exercised.

For actual submission after you have tested the flow:

```powershell
$env:LINKEDIN_DRY_RUN="false"
$env:COMPANY_WEBSITE_DRY_RUN="false"
python linkedin_main.py
```

## Chrome

Use the same established real-Chrome/CDP startup configuration as the Naukri project. Start Chrome with remote debugging on port 9222 and log into LinkedIn manually first.

## Direct search

```powershell
python linkedin_main.py "https://www.linkedin.com/jobs/search/?keywords=GenAI%20Engineer&location=Bengaluru%2C%20Karnataka%2C%20India"
```

## Important architecture rules

- Persistent `applications.db` is history, not a pre-open gate.
- Every unique discovered LinkedIn job is opened and checked live.
- Live `Applied` state prevents Apply.
- JD matching happens before Apply.
- Experience requirements are enforced truthfully for a fresher.
- AI never invents employment or personal facts.
- External ATS applications reuse the existing `CompanyWebsiteAgent`.
- The target limits submissions, not job discovery.
- Failed jobs do not terminate the whole scan.


## Separate LinkedIn Chrome profile
LinkedIn is configured to use CDP port 9223 and the dedicated `chrome-linkedin-profile` directory. Naukri remains on port 9222 and its profile is untouched. Log into LinkedIn with `kudireanuroop@gmail.com` in the new Chrome window on first run.

Start only Chrome: `START_LINKEDIN_CHROME_ONLY.ps1`
Start Chrome + agent: `START_LINKEDIN_AND_CHROME.ps1`
Run dry-run after Chrome is ready: `python linkedin_main.py --dry-run`
