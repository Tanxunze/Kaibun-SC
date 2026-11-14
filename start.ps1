param([switch]$Rebuild, [switch]$Help)
$ErrorActionPreference = 'Stop'
$launcherPython = Join-Path $PSScriptRoot 'backend/.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $launcherPython)) {
    if (-not (Get-Command uv -ErrorAction SilentlyContinue)) { throw 'Install uv and reopen PowerShell, then try again.' }
    Push-Location (Join-Path $PSScriptRoot 'backend')
    try { uv sync --locked; if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' } } finally { Pop-Location }
}
$launcherArgs = @((Join-Path $PSScriptRoot 'start.py'))
if ($Rebuild) { $launcherArgs += '--rebuild' }
if ($Help) { $launcherArgs += '--help' }
& $launcherPython @launcherArgs
exit $LASTEXITCODE
