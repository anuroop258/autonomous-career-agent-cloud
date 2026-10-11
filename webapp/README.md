# Career Agent Control Panel — connected to the current job-agent project

This `webapp/` is now embedded inside the current `easy_apply_arch_fix` repository.

- `frontend/`: React + TypeScript + Vite UI
- `backend/`: FastAPI adapter for the current `main.py`, `applications.db`, resume builder, Q&A memory, and CDP ports
- The backend does **not** replace LinkedIn/Indeed/Naukri logic. It starts the real `main.py` entrypoint and reads the same project files.

### Run backend
```powershell
cd C:\path	o\easy_apply_arch_fix
py -m pip install -r webapp\backend\requirements.txt
py -m uvicorn webapp.backend.main:app --host 127.0.0.1 --port 8000
```

### Run frontend
```powershell
cd webapp\frontend
npm install
npm run dev
```

Open `http://localhost:5175`.

### Important
The current agent does not implement recruiter outreach/approvals as a real subsystem, so those UI areas are intentionally not backed by fabricated records. LinkedIn, Indeed, Naukri, Shine, TimesJobs, Glassdoor, applications, resume tailoring, Custom Q&A, CDP status, automation control, and logs use this repository's actual runtime/data.

### Connected features in this build

Dashboard, Job Search, Jobs, Applications, Resume Tailoring, Custom Q&A, Browser/CDP, Logs, and Settings are wired to the current repository. Recruiter/outreach/approval pages from the original UI are left in the source but are intentionally not exposed in the sidebar because those services are not part of the current automation code.

## Legacy job metadata refresh

Older application DB rows may predate company/description fields. The dashboard now migrates those columns automatically. In Resume Tailoring, **Refresh Job Data** reads the already-open matching job tab over the portal CDP connection and stores company/title/description without clicking Apply or closing the browser.


### Added portal agents

The unified control panel includes Naukri, Indeed, LinkedIn, Shine, TimesJobs, and Glassdoor. Shine, TimesJobs, and Glassdoor attach to the existing Chrome CDP session at `127.0.0.1:9222`; LinkedIn uses `9232`. The combined frontend runs at `http://localhost:5175` and the API remains at `http://127.0.0.1:8001`.
