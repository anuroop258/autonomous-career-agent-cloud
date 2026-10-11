$ErrorActionPreference = 'Stop'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
if (-not (Test-Path $chrome)) { throw "Google Chrome not found at $chrome" }
$userData = Join-Path $env:LOCALAPPDATA 'NaukriAgentRealChrome'
Start-Process -FilePath $chrome -ArgumentList @('--remote-debugging-port=9222', "--user-data-dir=$userData", '--profile-directory=Default')
Start-Sleep -Seconds 2
python main.py
