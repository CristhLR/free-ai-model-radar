# Project state

## Goal
Discover and validate changing free AI API models, then feed useful verified changes into FreeLLMAPI for DeepSeek Harness.

## Decisions
- FreeLLMAPI handles routing, quotas, fallback, unified /v1 and DSH setup.
- Radar stores its own discovery history in SQLite.
- Python stdlib first; avoid dependencies until needed.
- JEV remains disabled by default.

## Current phase
MVP discovery pipeline.

## Next
1. Prove OpenRouter official catalog scan + diff.
2. Add source registry and scheduled incremental checks.
3. Add FreeLLMAPI config/export adapter only for gaps not already covered upstream.
4. Add more official sources, then community discovery.
