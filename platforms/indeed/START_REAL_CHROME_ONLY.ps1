$ErrorActionPreference = 'Stop'
$chrome = 'C:\Program Files\Google\Chrome\Application\chrome.exe'
if (-not (Test-Path $chrome)) { throw "Google Chrome not found at $chrome" }
$userData = Join-Path $env:LOCALAPPDATA 'NaukriAgentRealChrome'
Write-Host "Starting real Chrome for Indeed on CDP 9222..."
& $chrome --remote-debugging-port=9222 --user-data-dir=$userData --profile-directory='Default'
