# Autonomous Career Agent

A multi-platform job-search and application workspace. It connects job discovery, job-description screening, portal-specific application workflows, job-focused resume tailoring, reusable application answers, and a React dashboard backed by FastAPI.

**Website:** [https://autonomous-career-agent-cloud.pages.dev/#/](https://autonomous-career-agent-cloud.pages.dev/#/)  
**GitHub:** https://github.com/anuroop258/autonomous-career-agent-cloud

## Capabilities

- **Multi-portal agents:** separate integrations for Naukri, Indeed, LinkedIn, Shine, TimesJobs, and Glassdoor.
- **Job screening:** evaluate available job descriptions against configured profile information and role requirements, including experience and seniority checks.
- **Application workflows:** preserve portal-specific flows for native applications and validated external employer routes. A click is not treated as proof of a completed submission.
- **Resume tailoring:** prepare a job-specific resume from the existing master resume and profile material. The documented deterministic path selects and reorders existing skills and projects; it should not invent experience or qualifications.
- **Custom Q&A:** save reusable question-and-answer pairs for application forms. Questions that cannot be answered from known profile facts can remain for manual review.
- **Career workspace:** the dashboard includes job search, jobs, applications, tracking, resume tailoring, recruiter discovery, outreach, follow-ups, approvals, browser/CDP status, logs, Custom Q&A, and settings.
- **Local and cloud components:** run the dashboard locally, or explore the separate Cloudflare control-page and API/worker deployment configurations.

Portal implementations are not identical: each has its own application flow, browser behavior, and current integration boundaries. See the platform documentation before relying on a specific route.

## Architecture

```text
Job portals
    |
    v
Platform-specific agents
(Naukri / Indeed / LinkedIn / Shine / TimesJobs / Glassdoor)
    |
    +-- Job-description matching and eligibility checks
    +-- Portal-specific application state machines
    +-- Resume tailoring and Custom Q&A
    +-- Application and run data
             |
             v
        FastAPI backend
             ^
             | HTTP API
             v
   React + TypeScript + Vite dashboard
```

### Main components

| Path | Responsibility |
|---|---|
| `main.py` | Unified CLI launcher for portal agents |
| `platforms/` | Portal-specific agents, flows, storage and regression tests |
| `jd_matcher.py` | Shared job-description matching |
| `resume_integration.py`, `resume_tailer.py` | Resume generation and tailoring integration |
| `custom_qa_store.py`, `custom_qa_cli.py` | Persistent Custom Q&A and CLI |
| `webapp/backend/main.py` | FastAPI control and data API |
| `webapp/frontend/` | React, TypeScript and Vite dashboard |
| `functions/`, `free-cloud-control/` | Cloudflare Pages Functions and lightweight run-control page |
| `cloud_worker.py`, `cloud_queue.py`, `render.yaml` | Separate API/worker deployment candidate |

## Technology

**Python · Playwright · FastAPI · React · TypeScript · Vite · SQLite · PostgreSQL · Cloudflare Pages Functions · Cloudflare D1 · GitHub Actions**

## Run locally on Windows

### Prerequisites

- Python 3.11 or newer
- Node.js and npm
- Google Chrome
- A logged-in browser session for the portal being tested

### 1. Install dependencies

From the repository root:

```powershell
py -m pip install --upgrade pip
py -m pip install -r requirements.txt -r webapp\backend\requirements.txt
py -m playwright install chromium
```

### 2. Start the dashboard

```powershell
.\START_WEBAPP.cmd
```

The launcher installs frontend dependencies with `npm ci` when they are missing, then starts the FastAPI and Vite processes.

- Dashboard: http://127.0.0.1:5175
- API: http://127.0.0.1:8001

Open the dashboard after Vite reports that it is ready.

### Start services manually

Backend, from the repository root:

```powershell
py -m uvicorn webapp.backend.main:app --host 127.0.0.1 --port 8001
```

Frontend, in another terminal:

```powershell
cd webapp\frontend
npm ci
npm run dev -- --host 127.0.0.1 --port 5175 --strictPort
```

## Run a portal agent directly

The agent attaches to an existing Chrome session. Start Chrome with the relevant remote-debugging port and a dedicated browser profile, then run the selected portal.

For Naukri or Indeed, the documented CDP port is `9222`:

```powershell
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
$profile = "$env:LOCALAPPDATA\NaukriAgentRealChrome"
Start-Process -FilePath $chrome -ArgumentList @('--remote-debugging-port=9222', "--user-data-dir=$profile", '--profile-directory=Default')
py main.py naukri
```

LinkedIn uses a separate CDP port, `9232`:

```powershell
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
$profile = "$env:LOCALAPPDATA\LinkedInAgentRealChrome"
Start-Process -FilePath $chrome -ArgumentList @('--remote-debugging-port=9232', "--user-data-dir=$profile", '--profile-directory=Default')
py main.py linkedin
```

The unified launcher also accepts `indeed`, `shine`, `timesjobs`, and `glassdoor` as portal arguments. Check each platform's README for its specific behavior and limitations. Avoid running multiple agents against the same CDP browser session unless their browser contexts are explicitly isolated.

## Direct company-site flow

The direct company-site entry point accepts a specific application URL. Fill-only is the default; final submission requires the explicit `--submit` option.

```powershell
py main.py company-fill "https://example.com/careers/job" --platform linkedin --port 9232
```

## Cloud deployment configurations

The repository contains two separate cloud approaches. They should not be confused with one another or treated as proof of a live, fully validated deployment.

### Cloudflare Pages + D1 + GitHub Actions

`free-cloud-control/` contains a lightweight run-control page and Pages Functions. D1 stores task state; a manually dispatched GitHub Actions workflow runs a selected existing portal agent on a temporary Linux runner.

This is **not** a full migration of the React/FastAPI dashboard. It has separate encrypted private-data repository requirements, workflow secrets, runner limits, and portal-session constraints. Follow [FREE_DEPLOY_NO_CARD.md](FREE_DEPLOY_NO_CARD.md) and [free-cloud-control/README.md](free-cloud-control/README.md).

### Split API and browser worker

`render.yaml`, `cloud_worker.py`, and `cloud_queue.py` describe a separate API/worker setup using PostgreSQL for task coordination and shared state. See [DEPLOY_CLOUD.md](DEPLOY_CLOUD.md) for its architecture and remaining validation requirements.

A deployment configuration in source control does not establish that a live portal run has succeeded. Verify authentication, session import, task completion, data persistence, and manual security challenges in the target environment before relying on cloud automation.

## Safety and privacy

- Keep `.env` files, API keys, browser cookies, Playwright storage states, profile data, application databases, resumes, and generated personal documents out of public source control.
- Review `git status` and staged file lists before committing.
- Do not bypass CAPTCHA, OTP, MFA, or other portal security challenges. Complete required verification manually.
- Do not guess answers to personal, education, employment, or eligibility questions. Use known profile facts and saved answers; stop for review when a truthful answer is unavailable.
- Verify the destination, resume version, and application status. A button click alone is not evidence that an application was submitted.
- Start with a small, supervised run before increasing any target.

## Tests

The repository includes regression tests for portal behavior, application routing, profile and question handling, resume tailoring, and deployment boundaries.

Run the root test suite:

```powershell
py -m pytest tests -q
```

Run a selected portal regression test explicitly when needed:

```powershell
py -m pytest platforms\indeed\test_qa_regression.py -q
```

Some tests require browser dependencies, portal sessions, or fixtures. Passing unit tests do not replace a supervised live workflow check.

## Project guides

- [Start here](README_START_HERE.md)
- [Run commands](RUN_COMMANDS.md)
- [Platform-specific application workflows](PLATFORM_APPLICATION_WORKFLOWS.md)
- [Desktop launcher](DESKTOP_APP.md)
- [Free cloud control setup](FREE_DEPLOY_NO_CARD.md)
- [Split cloud deployment guide](DEPLOY_CLOUD.md)