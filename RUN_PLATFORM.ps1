
param(
  [ValidateSet("naukri","indeed","linkedin")]
  [string]$Platform = "naukri"
)

if ($Platform -eq "linkedin") {
  $Port = 9232
  $Profile = "$env:LOCALAPPDATA\LinkedInAgentRealChrome"
} else {
  $Port = 9222
  $Profile = "$env:LOCALAPPDATA\NaukriAgentRealChrome"
}

Write-Host "Platform: $Platform"
Write-Host "CDP port: $Port"
Write-Host "Browser profile: $Profile"

# Launch only the browser here. The Python command is kept separate so the platform
# implementation can decide how to connect to its own session.
& "C:\Program Files\Google\Chrome\Application\chrome.exe" `
  "--remote-debugging-port=$Port" `
  "--user-data-dir=$Profile" `
  "--profile-directory=Default"

python main.py $Platform
