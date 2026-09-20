$ErrorActionPreference = 'SilentlyContinue'
$root = 'C:\Users\cdavi\free-ai-model-radar'
Set-Location $root
$existing = Get-NetTCPConnection -LocalPort 3002 -State Listen -ErrorAction SilentlyContinue
if ($existing) { exit 0 }
for ($i = 0; $i -lt 30; $i++) {
    if (Test-NetConnection 127.0.0.1 -Port 31415 -InformationLevel Quiet) { break }
    Start-Sleep -Seconds 1
}
$env:PYTHONIOENCODING = 'utf-8'
python -m src.free_ai_model_radar.smart_gateway *>> "$root\data\smart-gateway.log"
