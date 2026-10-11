# Concurrency + Restart Fix V19

Compared with the earlier workflow, the control panel now preserves independent platform runs.

- LinkedIn, Indeed, and Naukri may run concurrently.
- Naukri + Indeed intentionally share CDP 9222; they attach to the existing shared Chrome session.
- LinkedIn remains isolated on CDP 9232.
- Stop terminates only the selected process tree(s) owned by the automation runner, not Chrome/CDP.
- A stopped platform can be started again immediately without closing Chrome.
- Portal launch no longer spawns a duplicate Chrome process when its CDP port is already connected.
- The launcher no longer overrides ENABLE_GEMINI / OLLAMA_ENABLED, restoring the prior workflow's environment behavior.
