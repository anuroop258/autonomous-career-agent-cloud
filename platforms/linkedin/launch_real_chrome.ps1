# Launch the user's installed Google Chrome with a CLONED copy of the
# existing Chrome profile, so the agent can use the existing Google/Naukri
# login without asking for credentials again.
#
# IMPORTANT: Close all normal Chrome windows before running this script.

$ErrorActionPreference = 'Stop'

$chromeCandidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)

$chrome = $chromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
    throw "Installed Google Chrome was not found."
}

$source = Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data'
$target = Join-Path $env:LOCALAPPDATA 'NaukriAgentChrome'

if (-not (Test-Path $source)) {
    throw "Chrome user data was not found at: $source"
}

if (Test-Path $target) {
    Write-Host "Removing previous agent Chrome profile..."
    Remove-Item -LiteralPath $target -Recurse -Force
}

Write-Host "Copying your existing Chrome profile to the agent profile..."
New-Item -ItemType Directory -Path $target | Out-Null
robocopy $source $target /E /COPY:DAT /R:1 /W:1 /NFL /NDL /NP | Out-Null
if ($LASTEXITCODE -ge 8) {
    throw "Profile copy failed (robocopy exit code $LASTEXITCODE)."
}

Write-Host "Starting installed Google Chrome (not Chrome for Testing)..."
& $chrome --remote-debugging-port=9222 --user-data-dir="$target" --profile-directory="Default"
