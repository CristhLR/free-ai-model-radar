$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$out = (& python -m src.free_ai_model_radar.cli watch 2>&1 | Out-String).Trim()
$exitCode = $LASTEXITCODE

if ($exitCode -ne 0 -or ($out -and $out -ne "[]")) {
    $logDir = Join-Path $repo "data"
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
    $stamp = (Get-Date).ToString("o")
    Add-Content -Path (Join-Path $logDir "runner.log") -Value "[$stamp] exit=$exitCode"
    Add-Content -Path (Join-Path $logDir "runner.log") -Value $out
}

exit $exitCode
