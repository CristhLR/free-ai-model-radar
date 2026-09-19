$ErrorActionPreference = "Stop"
$project = "C:\Users\cdavi\free-ai-model-radar"
Set-Location $project

$logDir = Join-Path $project "data"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$log = Join-Path $logDir "freellmapi-runner.log"

try {
    $output = python -m src.free_ai_model_radar.freellmapi_sync 2>&1
    $output | Out-File -FilePath $log -Append -Encoding utf8
    exit $LASTEXITCODE
}
catch {
    $_ | Out-File -FilePath $log -Append -Encoding utf8
    exit 1
}
