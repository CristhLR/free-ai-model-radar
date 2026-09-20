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
$env:TOKENIZERS_PARALLELISM = 'false'
$env:HF_HOME = Join-Path $root 'data\hf-cache'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:HF_HUB_DISABLE_XET = '1'
$env:HF_HUB_DISABLE_SYMLINKS_WARNING = '1'
$python = Join-Path $root '.venv-smart\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
& $python -m src.free_ai_model_radar.smart_gateway *>> "$root\data\smart-gateway.log"
