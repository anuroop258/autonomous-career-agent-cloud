# No-card cloud run prototype for Autonomous Career Agent

This kit adds an **on-demand remote browser runner**, not a full port of the original React/FastAPI dashboard. It deliberately leaves the existing application code intact. The small Cloudflare control page starts/stops one run and shows its status/log tail; the legacy analytics, recruiter, resume and job pages are not migrated in this phase.

## What this changes / what it does not

- Cloudflare Pages hosts `free-cloud-control/public/index.html` and its Pages Functions.
- Cloudflare D1 stores only run state and short log tails.
- Cloudflare Pages Functions dispatch a manual GitHub Actions workflow.
- GitHub Actions starts a temporary Linux browser, restores a session from an **encrypted private data bundle**, runs one existing portal agent, then encrypts the updated profiles, SQLite application history, resumes and session state back into the private data repository.
- It uses no Render resources and no persistent cloud browser. The source repository must remain private. The private data repository contains only `career-agent-private.enc`, not plaintext personal files.

## Hard limitations

- The free page is a lightweight run controller, **not the previous complete React analytics dashboard**. Porting every API endpoint, analytics view and data table to D1 is a separate migration.
- GitHub-hosted runners are temporary and the free allowance for private repositories is finite (commonly 2,000 standard runner minutes/month on GitHub Free; verify the current quota in your account). This workflow has a 60-minute timeout and caps runs at 1–5 target applications. Install time also consumes runner minutes.
- Headless login sessions can expire; MFA/CAPTCHA or bot checks may prevent a run. There is no remote interactive browser in this first version. Do not expect every portal to work unattended.
- Chromium's login storage is a credential. Only include it inside the encrypted bundle and keep the Fernet key in GitHub Actions secrets. Never commit plaintext `cloud_private/`, profiles, application databases, or resumes.
- Do not run multiple portal workflows simultaneously. The queue page rejects a new run while a current one is active.

## 1. Add these files to the existing local source repo

Extract this kit **on top of** `C:\Users\Anuroop\Downloads\jobnewfrontend_cloud_worker_split` and allow new files to merge. Do not replace the original source tree. Copy the content of `FREE_DEPLOY_GITIGNORE_ADD.txt` to the end of the existing root `.gitignore`.

Then from the project folder run:

```powershell
git status --short
```

Check the new files are listed and that `profile.json`, `applications.db`, `resume/`, `resume_versions/`, PDFs, and `.env` are still ignored. Commit and push only the **source additions**:

```powershell
git add .github/workflows/free-cloud-run.yml free-cloud-control tools/private_bundle.py tools/export_cloud_session_local.py tools/restore_cloud_session.py tools/start_cloud_browser.py tools/set_run_limit.py tools/run_cloud_agent.py tools/report_cloud_status.py FREE_DEPLOY_NO_CARD.md FREE_DEPLOY_GITIGNORE_ADD.txt
git add .gitignore
git diff --cached --name-only
git status --short
```

Review both outputs for personal data before committing:

```powershell
git commit -m "Add no-card remote browser runner prototype"
git push origin main
```

## 2. Create the private encrypted-data repository

Create a second repository in GitHub named `autonomous-career-agent-private-data` and make it **Private**. It should contain only one encrypted file, `career-agent-private.enc`.

The project needs Python dependencies and Playwright locally for session export. In PowerShell in the main project folder:

```powershell
py -m pip install cryptography playwright
```

Start Chrome with the existing remote-debugging port for the portal you want to test. For Naukri (first recommended test), open a separate Chrome profile, log in manually and leave it open:

```powershell
$chrome = "$env:ProgramFiles\Google\Chrome\Application\chrome.exe"
if (!(Test-Path $chrome)) { $chrome = "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe" }
$profile = "$env:LOCALAPPDATA\CareerAgentExport9222"
Start-Process -FilePath $chrome -ArgumentList @('--remote-debugging-port=9222', "--user-data-dir=$profile", 'https://www.naukri.com')
```

Once logged in, export only the Naukri session locally (this creates a **sensitive plaintext** file that must not be committed):

```powershell
py tools\export_cloud_session_local.py naukri
```

Create the encrypted private bundle outside the source repository:

```powershell
py tools\private_bundle.py encrypt --root . --output ..\career-agent-private.enc --generate-key
```

Copy the generated key somewhere safe temporarily. It is the Fernet key, not a GitHub token. Copy `..\career-agent-private.enc` into a new local clone of the private data repository. Commit and push only that encrypted file. Do not put the key or plaintext sessions into that repository.

The bundle encrypts these existing local files when present: root and portal profile JSON, root and portal application databases (+ SQLite WAL/SHM files), `resume/`, `resume_versions/`, `resume_content_bank.json`, and `cloud_private/sessions/*.json`.

## 3. Give the workflow restricted access to the private-data repo

Create a **fine-grained personal access token** with access only to `autonomous-career-agent-private-data`, permissions `Contents: Read and write` and metadata read. Add it to the source repo's Settings → Secrets and variables → Actions as secret:

- `CAREER_AGENT_DATA_TOKEN`
- `CAREER_AGENT_PRIVATE_BUNDLE_KEY` (the Fernet key printed above)
- `CLOUD_CONTROL_API_KEY` (the same API key you configure on Cloudflare Pages)

Add repository variable:

- `CAREER_AGENT_DATA_REPO` = `anuroop258/autonomous-career-agent-private-data`

The workflow checks out this repository, decrypts the bundle only on the temporary runner, and pushes the **re-encrypted** updated bundle back after the run. The token needs write permission because DB/session updates must persist.

## 4. Create the Cloudflare D1 database and Pages app

1. Create a free Cloudflare account; don't activate a paid plan or R2.
2. In Workers & Pages → D1, create a database named `career-agent-control`.
3. Open its console and execute the complete `free-cloud-control/schema.sql` SQL.
4. In Workers & Pages → Pages, connect the existing private GitHub repository `anuroop258/autonomous-career-agent-cloud`.
5. Set root directory to `free-cloud-control`, leave build command blank, set build output directory to `public`, and deploy.
6. In that Pages project's Settings → Functions, add a D1 database binding named `DB` pointing to `career-agent-control` (for Production; also Preview if you use preview builds).
7. Under Settings → Variables and Secrets, configure:

   - `DASHBOARD_API_KEY` — a strong random key (generate with `py -c "import secrets; print(secrets.token_urlsafe(32))"`).
   - `GH_DISPATCH_TOKEN` — a separate fine-grained token for the source repo, permission `Actions: Read and write`, Metadata read. This authorizes the page to start workflows.
   - `GH_REPO_OWNER` = `anuroop258`
   - `GH_REPO_NAME` = `autonomous-career-agent-cloud`
   - `GH_WORKFLOW_FILE` = `free-cloud-run.yml`

   The same `DASHBOARD_API_KEY` must match the GitHub Actions secret `CLOUD_CONTROL_API_KEY`. Keep both tokens out of source code.

8. After Pages deploys, add this **repository variable** in GitHub source repo Settings → Secrets and variables → Actions:

   - `CLOUD_CONTROL_API_BASE` = the full Pages URL, e.g. `https://your-project.pages.dev`

## 5. First test

Open the Pages URL, enter the `DASHBOARD_API_KEY` in the page and save it. Choose Naukri and target `1`. Confirm that the imported Naukri session is valid; then start the run. Check the control page's status/log tail and GitHub Actions run logs. Wait for the workflow to finish before starting another portal.

If the runner says the session is invalid or a verification challenge appears, stop there and fix the session first. If the bundle fails to decrypt, do not regenerate the key; restore the matching secret. If the private data push fails, the job may run but updated deduplication/application state will not persist, so do not start a second run until the data commit is fixed.

## 6. GitHub free usage

Check GitHub Settings → Billing and licensing → Usage before running many tests. Private-repository standard runner minutes are limited and package installation consumes part of them. Keep tests small. The workflow has a 60-minute hard timeout and an application target maximum of 5; start with 1.

## Official references

- Cloudflare Pages Functions: https://developers.cloudflare.com/pages/functions/
- Cloudflare D1: https://developers.cloudflare.com/d1/
- GitHub Actions workflow dispatch: https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event
- GitHub Actions billing: https://docs.github.com/en/billing/concepts/product-billing/github-actions
