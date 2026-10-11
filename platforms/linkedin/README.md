# Naukri Personal Job Application Agent — v15

This version is designed for users already logged into Google/Naukri in their normal installed Google Chrome.

## Important

The agent itself does **not** receive your Google password or OTP.

Because recent Chrome versions restrict remote debugging of the normal Chrome user-data directory, this version first makes a local copy of your existing Chrome profile and launches the **installed Google Chrome** binary against that copy. Your existing Google/Naukri session cookies can therefore be reused without entering credentials into the agent.

### First run

1. Close **all normal Google Chrome windows**.
2. Open PowerShell in this folder.
3. Run:

```powershell
.\launch_real_chrome.ps1
```

4. A new window should say **Google Chrome**, NOT **Google Chrome for Testing**.
5. Check Naukri in that window. If you are already logged in, leave it open.
6. In a second PowerShell window, from this folder:

```powershell
.venv\Scripts\activate
python main.py "https://www.naukri.com/python-developer-jobs"
```

Keep:

```text
DRY_RUN=true
MAX_JOBS=3
USE_EXISTING_CHROME=true
CHROME_CDP_URL=http://127.0.0.1:9222
```

## If Naukri is not logged in

Log into Naukri normally in the new **Google Chrome** window. If Google asks for verification, complete it yourself. Do not give credentials to the agent.

Leave the browser open while the agent runs.

## JD matching

Before Apply, the agent scores the visible job description against the configured profile and target roles. Jobs below the configured threshold are skipped. Explicit mandatory experience above the candidate's experience is also rejected.

## Why this is different from v7

v7 could accidentally involve Playwright/Chrome-for-Testing during the authentication flow. v8 explicitly launches the installed Google Chrome executable and uses a cloned copy of the user's Chrome profile.

## Safety

- No CAPTCHA/OTP/security bypass.
- Unknown personal questions are not guessed.
- The agent uses configured truthful answers only.
- `DRY_RUN=true` should be used for testing.


### Chrome / Naukri login
Use `START_REAL_CHROME_ONLY.cmd` after closing all Chrome windows. It launches Google Chrome
with the normal Chrome profile and exposes CDP on port 9222. This build does not create or use
a separate `NaukriAgentRealChrome` profile, so the normal Chrome/Naukri login is retained.
After Chrome is open and Naukri is logged in, run `python main.py` from the venv.


### v15.2 changes
- Detects Naukri's "There was an error while processing your request" Apply response and records it without crashing the run.
- Requires a meaningful AI/GenAI/ML signal before a job can qualify; generic C++/Java/AWS/Git matches alone no longer make a role eligible.
- Removes duplicate external-job counter increment.
- Keeps persistent deduplication, fresher/0-year eligibility, native conversational Apply handling, and CAPTCHA/OTP/security intervention pauses.


### v15.3 Apply interaction fix
The Naukri Apply control is targeted more precisely and a single controlled retry is attempted when the known processing-error banner appears. A click is never treated as a submitted application; the existing conversational flow and final status verification remain in place.


### v15.4 question controls
Yes/No and other choice questions are clicked as visible options/buttons/radios instead of being typed into an input. Numeric/text questions are entered into editable fields. The application panel also has an explicit success-state detector.


UNIVERSAL QA v17
----------------
The application QA layer is UI-adaptive rather than tied to one Naukri selector.
It dynamically discovers visible inputs, textareas, contenteditable controls,
comboboxes, selects, radios, checkboxes, buttons, options, labels and chips.
It scores controls by their surrounding label/question so special controls such
as CTC fields can be distinguished from unrelated inputs. It verifies answers
before continuing and never uses the question text as a fallback answer.
Unknown/unconfigured questions remain safely blocked.


V18 PROFILE-GROUNDED DYNAMIC QA
--------------------------------
The QA system is now split into:
  profile_reasoner.py -> decides WHAT truthful answer the question requires.
  qa_engine.py        -> compatibility wrapper for the existing agent.
  naukri_agent.py     -> discovers the current UI and decides HOW to enter it.

Dynamic reasoning:
  - If GEMINI_API_KEY is configured, the reasoner sends the question, visible
    options, and non-contact profile facts to Gemini. Gemini is the primary
    reasoning backend.
  - GEMINI_MODEL defaults to gemini-3-flash-preview and can be overridden.
  - OPENAI_API_KEY remains supported as a compatibility fallback.
  - The model must output structured JSON and is explicitly prohibited from
    inventing facts or professional experience.
  - Visible option labels are validated against the actual page before use.
  - Without an API key, a conservative local semantic fallback handles common
    profile facts and skill matching; it returns UNKNOWN rather than guessing.

PowerShell setup (Gemini):
  $env:GEMINI_API_KEY="YOUR_GEMINI_KEY"
  $env:GEMINI_MODEL="gemini-3-flash-preview"
  $env:DRY_RUN="true"
  python main.py

The API key is read only from the environment and is not stored in profile.json.


V18.2 EXTERNAL COMPANY-SITE APPLICATION FILLING
------------------------------------------------
Previously, whenever "Apply" led off Naukri to a company's own career site
(Greenhouse, Lever, Workday, a custom ATS, etc.), the agent skipped and
closed that tab. It now attempts to fill that form too, using the same
truthful profile data:

  - Text/email/phone/city/state/country/expected-CTC/experience-style
    fields are matched by their placeholder, aria-label, name attribute,
    or associated <label> text, and filled from profile.json.
  - A field is only filled if it can be confidently matched to a known
    profile value; nothing is invented. A field that already has a value
    is never overwritten.
  - A "Submit / Apply Now / Continue" style control is only clicked when
    DRY_RUN=false. With DRY_RUN=true (the default) the form is filled but
    never submitted.
  - If a CAPTCHA/OTP/security check is detected before or after filling,
    the agent stops touching that page and leaves it for you.
  - Any error while handling an external form (unexpected page structure,
    a control that can't be set, etc.) is caught locally. It is logged,
    the run does NOT crash, and the agent moves on to the next job.

Important behavior change: the agent now NEVER closes an external
company-site tab, whether the form was filled successfully, blocked by a
CAPTCHA/OTP, or hit an error. That tab is left open in your browser so you
can see exactly what was filled and finish/verify/submit manually if you
want to, while the agent continues processing the rest of the job list in
other tabs. Only the original Naukri job-listing tab (when Apply opened a
separate popup/tab) is closed once the external tab takes over.

The end-of-role summary line now reports external outcomes in more detail:
  external attempted=N (filled=X, errored=Y)

### Resume upload
Configure `resume.path` in `profile.json` (default: `resume.pdf`). Visible external file inputs are detected and the configured resume is uploaded when appropriate. CAPTCHA/OTP/security controls are not interacted with.

### v20 resume chooser support
External resume upload now supports both direct `input[type=file]` controls and visible controls such as “Upload from device” that trigger a Playwright file chooser. The configured resume is selected programmatically and the page is checked for a filename/success indicator afterward. CAPTCHA/OTP/security controls are not clicked.

### Resume folder support
`resume.path` may point to a resume file or a folder. If it points to a folder, the agent considers only PDF/DOC/DOCX files and deterministically prefers filenames containing `resume`, then `cv`, then the candidate name, with PDF preferred as a tie-breaker. For external sites it first uses a real file input when available; otherwise it performs one controlled click on a matching “Upload from device” control and intercepts the Playwright file chooser.

### v22 stability fix
Before clicking Apply, the agent detects visible `mailto:` application routes and skips them without opening Outlook or another mail client. This is intentionally handled before any Apply click.

### v24 final-flow fixes
- Compound AI internship/academic-project/personal-project/hackathon questions resolve to Yes when supported by the documented projects.
- Dry-run now clicks intermediate Naukri Save/Continue/Next controls so answers such as graduation year 2026 are actually committed and the flow advances; only final submission remains blocked.
- External sites get one controlled Apply click before resume upload/form filling.
- External resume upload happens after landing-page Apply navigation.

### v27 clean consolidation
This build consolidates the native question state machine and external application state machine. Intermediate Save/Continue/Next controls are allowed during dry-run; final submission remains blocked. Native answers are verified before advancing. External pages are classified as landing pages vs candidate forms, with one controlled Apply click on landing pages, then resume upload, profile-backed field filling, verification, and final submission only when DRY_RUN=false. Mailto links and security challenges are not automated.
