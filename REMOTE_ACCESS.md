# Use the Career Agent from anywhere (phone / other laptop)

The agent, your data and your logged-in Chrome stay **on your PC**. A secure tunnel lets
you open the same control panel from any browser. The page is protected by an access key.

## Quick start (Cloudflare Tunnel, free)
1. Install once: `winget install Cloudflare.cloudflared`
2. Double-click **START_REMOTE.cmd**.
3. It prints your **access key** and opens a tunnel window showing an address like
   `https://random-words.trycloudflare.com`.
4. Open that address on your phone/laptop, type the key, done. Dashboard, Jobs,
   Applications, Resume Tailoring, Custom Q&A, Start/Stop automation all work.

Your PC must stay on, awake and online, and Chrome must be running as usual for applying.

## Safer alternative: Tailscale (no public address at all)
1. Install Tailscale on the PC and on your phone, sign in to the same account.
2. Run START_REMOTE.cmd (ignore the Cloudflare message).
3. In a terminal on the PC: `tailscale serve --bg 8001`
4. Open the `https://<pc-name>.<tailnet>.ts.net` address on your phone, enter the key.
Only your own devices can even reach it.

## How it is protected
- Every `/api/*` request needs the key (header `X-API-Key`). Without it: 401.
- 10 wrong keys from one client in 5 minutes -> locked out for a few minutes.
- The backend listens only on 127.0.0.1; the tunnel is the only way in.
- API docs/schema are hidden while the key is on; `/api/health` reveals no paths.
- CORS is no longer `*`: only the local UI (and origins you add with
  `CAREER_AGENT_ALLOWED_ORIGINS`) are accepted.
- Your files (`profile.json`, `applications.db`, resumes) are never served as web files.

## Important
- **The key is full control** (it can start/stop applying and read your profile and resumes).
  Don't share it. To change it, delete `webapp\runtime\remote_api_key.txt` and run
  START_REMOTE.cmd again. "Lock" (bottom-right of the page) forgets the key on that device.
- Free Cloudflare quick-tunnel addresses change every time you start the tunnel and are
  public (the login page is visible, the data is not). For a fixed address or an extra
  login in front, create a named tunnel + Cloudflare Access (free).
- Normal local use is unchanged: `START_WEBAPP.cmd` still works with no key.
- The URL key is accepted only for the resume-PDF download link (browsers can't send
  headers on a link); everything else uses the header.

## Manual run (without the script)
```
set CAREER_AGENT_API_KEY=<at least 16 characters>
py -m uvicorn webapp.backend.main:app --host 127.0.0.1 --port 8001
cloudflared tunnel --url http://127.0.0.1:8001
```
