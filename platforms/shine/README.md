# Shine Agent

Backend-only Shine automation adapter. No frontend connection is included in this phase.

## Baseline

The initial file set is replicated from the working Indeed platform adapter where the shared behavior is reusable:

- `storage.py`
- `profile.json`
- `role_config.json`
- `requirements.txt`
- `profile_reasoner.py`
- `qa_engine.py`
- `company_website_agent.py`

Shine-specific behavior lives in `shine_agent.py` and `shine_main.py`.

## Chrome

The agent attaches to an existing Chrome CDP session; it does not launch Chrome itself.

Default CDP:

`http://127.0.0.1:9222`

Override with `SHINE_CDP_PORT`.

## Run

From the repository root:

```powershell
python platforms/shine/shine_main.py
```

Optional direct target URL:

```powershell
python platforms/shine/shine_main.py https://www.shine.com/dashboard
```

The agent searches Shine using the visible `Enter Skills/Roles`, `Enter Location`, and `Search` controls when available, evaluates job detail pages with the shared JD matcher, checks the live `Applied` state, clicks the native `Apply` control, and records the final result in `platforms/shine/applications.db`.

The first version intentionally does not connect to the React/webapp frontend.
