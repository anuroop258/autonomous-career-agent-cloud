$ErrorActionPreference = "Stop"

$chromeCandidates = @(
    "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
    "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
    "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe"
)
$chrome = $chromeCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $chrome) { throw "Google Chrome executable not found." }

$port = 9223
$profileDir = Join-Path $PSScriptRoot "chrome-linkedin-profile"
New-Item -ItemType Directory -Force -Path $profileDir | Out-Null

Write-Host "Starting SEPARATE LinkedIn Chrome profile..."
Write-Host "Profile: $profileDir"
Write-Host "CDP port: $port"
Write-Host "Account: kudireanuroop@gmail.com"
Write-Host "Existing Naukri Chrome on 9222 is NOT modified."

# Only terminate a Chrome process that was launched with THIS dedicated profile.
$profileNeedle = ($profileDir -replace '\\','\\')
try {
    Get-CimInstance Win32_Process -Filter "Name='chrome.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and $_.CommandLine.Contains($profileDir) } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
} catch {}

# Fail fast if another process already owns 9223.
try {
    $existing = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port/json/version" -TimeoutSec 1
    if ($existing.StatusCode -eq 200) {
        Write-Host "Chrome CDP is already running on $port. Reusing it."
        exit 0
    }
} catch {}

$args = @(
    "--remote-debugging-port=$port",
    "--remote-debugging-address=127.0.0.1",
    "--user-data-dir=$profileDir",
    "--no-first-run",
    "--no-default-browser-check",
    "--new-window",
    "https://www.linkedin.com/"
)

$proc = Start-Process -FilePath $chrome -ArgumentList $args -PassThru
Write-Host "Chrome PID: $($proc.Id)"
Write-Host "Waiting for Chrome CDP on port $port..."

for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    try {
        $r = Invoke-WebRequest -UseBasicParsing "http://127.0.0.1:$port/json/version" -TimeoutSec 2
        if ($r.StatusCode -eq 200) {
            Write-Host "LinkedIn Chrome CDP is ready on $port."
            exit 0
        }
    } catch {}
    if ($proc.HasExited) {
        throw "LinkedIn Chrome exited before exposing CDP on port $port."
    }
}
throw "LinkedIn Chrome did not expose CDP on port $port."
