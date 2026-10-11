$ErrorActionPreference = "Stop"

$chromeCandidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)

$chrome = $chromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) {
    throw "Google Chrome executable not found."
}

Write-Host "Starting Chrome with your normal Chrome profile and CDP port 9222..."
Write-Host "Close all Chrome windows before running this script."

Start-Process -FilePath $chrome -ArgumentList @(
    "--remote-debugging-port=9222"
)

Write-Host "Chrome started. Log into Naukri if needed, then leave Chrome open."
