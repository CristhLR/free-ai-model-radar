# free-ai-model-radar

Incremental radar for free AI API models used alongside FreeLLMAPI and DeepSeek Harness.

## Scope
This project discovers, verifies and tracks free model/API changes. It does **not** reimplement FreeLLMAPI routing, failover, quota tracking or its OpenAI-compatible gateway.

## Current MVP
- SQLite model, event, source-check and API-check state
- OpenRouter official zero-price model scanner
- 22 official monitoring signals across major providers
- NEW / CHANGED / REMOVED diffs
- ETag / Last-Modified conditional requests
- normalized HTML fingerprints to suppress dynamic-page noise
- adaptive per-source scheduling with backoff as sources remain stable
- expected-change scheduling for known future changes
- separate expensive API-verification schedule
- bounded concurrent source checks
- Windows hourly runner that executes only due checks
- 5 discovery catalogs merged with deduplication and conflict tracking
- registration/action queue with official-link overrides
- JEV disabled by default

## Commands
```powershell
python -m src.free_ai_model_radar.cli scan openrouter
python -m src.free_ai_model_radar.cli sources
python -m src.free_ai_model_radar.cli schedule
python -m src.free_ai_model_radar.cli watch
python -m src.free_ai_model_radar.cli watch all
python -m src.free_ai_model_radar.cli api-schedule
python -m src.free_ai_model_radar.cli discover-catalogs
python -m src.free_ai_model_radar.cli prepare-actions
python -m src.free_ai_model_radar.cli registration-plan --limit 10
```

`watch` checks only sources whose `next_check_at` is due. `watch all` forces all configured sources.

## Windows scheduler
```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_windows_task.ps1
```

This creates the hourly `FreeAIModelRadar` task. The task itself is cheap: the internal scheduler skips every source that is not due.

## Safety
`FREE_ONLY=true` is the default policy. JEV remains opt-in with `USE_JEV=false`. Secrets and local SQLite/log files are ignored by Git.
