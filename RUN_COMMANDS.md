# Job Application Agent — Separate Platform Runs

The project uses **one profile/configuration** while keeping browser-debugging ports and
application commands separate.

## Naukri

Use the established real-Chrome profile on CDP port **9222**.

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9222 --user-data-dir="$env:LOCALAPPDATA\NaukriAgentRealChrome" --profile-directory="Default"
python main.py naukri
```

Or use the supplied launcher:

```cmd
START_REAL_CHROME_AND_AGENT.cmd
```

## Indeed

Run the Indeed application flow separately; do not reuse the LinkedIn CDP port.

```powershell
python main.py indeed
```

If a separate Indeed browser instance is required by the Indeed implementation, start it
with its own user-data directory while retaining the same application profile data.

## LinkedIn

LinkedIn uses CDP port **9232**, independently of Naukri.

```powershell
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9232 --user-data-dir="$env:LOCALAPPDATA\LinkedInAgentRealChrome" --profile-directory="Default"
python main.py linkedin
```

## Important

- **Naukri = 9222**
- **LinkedIn = 9232**
- Do not change the known-good Naukri 9222 setup while fixing application logic.
- Run only the desired platform command at a time unless the implementation explicitly
  isolates browser profiles.
- The shared profile is the application/profile configuration; browser CDP sessions remain
  platform-specific.

## Direct company-site fill

Use this for one exact company application URL. Fill-only is the default; `--submit` enables final submission.

```powershell
python main.py company-fill "https://example.com/careers/job#application-form" --platform linkedin --port 9232
```

RingTrunk example:

```powershell
python main.py company-fill "https://ringtrunk.com/careers/ai-engineer#application-form" --platform linkedin --port 9232
```
