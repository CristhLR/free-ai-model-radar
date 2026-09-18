# free-ai-model-radar

Incremental radar for free AI API models used alongside FreeLLMAPI and DeepSeek Harness.

## Scope
This project discovers, verifies and tracks free model/API changes. It does **not** reimplement FreeLLMAPI routing, failover, quota tracking or its OpenAI-compatible gateway.

## First MVP
- SQLite state/history
- official-source adapters
- free-only classification
- NEW / CHANGED / REMOVED diffs
- OpenRouter official catalog adapter

## Run
```powershell
python -m src.free_ai_model_radar.cli scan openrouter
python -m src.free_ai_model_radar.cli sources
python -m src.free_ai_model_radar.cli watch all
```

The watcher uses conditional requests (ETag / Last-Modified when supported) and normalized content fingerprints to avoid reporting unchanged pages. No API keys are required for the initial OpenRouter catalog scan or source watches.
