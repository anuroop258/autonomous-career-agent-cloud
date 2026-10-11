JOB AGENT - SHORT PATH / FIXED DEPENDENCY PACKAGE

1. Extract this ZIP to a short location, e.g.
   C:\job_agent

2. FIRST RUN:
   Double-click SETUP.cmd
   (or run: py -m pip install -r requirements.txt)

3. LinkedIn:
   Start Chrome on CDP 9232, then run:
   py main.py linkedin

4. Indeed:
   Start Chrome on CDP 9222, then run:
   py main.py indeed

5. Naukri:
   Start Chrome on CDP 9222, then run:
   py main.py naukri

6. Direct company form:
   py main.py company-fill "https://ringtrunk.com/careers/ai-engineer#application-form" --platform linkedin --port 9232

The launcher also auto-installs the Python Playwright package if it is missing.
No .venv, caches, or .pyc files are included, which keeps extraction short-path friendly.
