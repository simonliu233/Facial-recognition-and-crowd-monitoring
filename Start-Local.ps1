param([int]$Port = 5000, [switch]$NoBrowser, [switch]$Check)
$ErrorActionPreference = "Stop"
$projectRoot = $PSScriptRoot
$pythonCandidates = @(
    (Join-Path $projectRoot ".venv\Scripts\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python310\python.exe"),
    (Join-Path $env:LOCALAPPDATA "Programs\Python\Python311\python.exe")
)
$projectPython = $pythonCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $projectPython) {
    Write-Error "Install Python 3.10/3.11, create .venv, and install Python Page/requirements.txt."
    exit 1
}
$launchArgs = @("-B", (Join-Path $projectRoot "Python Page\run.py"), "--port", "$Port")
if ($NoBrowser) { $launchArgs += "--no-browser" }
if ($Check) { $launchArgs += "--check" }
& $projectPython @launchArgs
exit $LASTEXITCODE
