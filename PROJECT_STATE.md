# Project state

## Goal
Discover and validate changing free AI API models, then feed useful verified changes into FreeLLMAPI for DeepSeek Harness.

## Decisions
- FreeLLMAPI handles routing, quotas, fallback, unified /v1 and DSH setup.
- Radar stores its own discovery history in SQLite.
- Python stdlib first; avoid dependencies until needed.
- JEV remains disabled by default.

## Current phase
MVP discovery pipeline is working.

## Working now
- OpenRouter official free-model scan with NEW / CHANGED / REMOVED diff.
- SQLite model and source-check history.
- Source registry with FreeLLMAPI release, Groq models and Gemini pricing.
- Conditional HTTP checks with ETag / Last-Modified and normalized HTML fingerprints.
- 4 unit tests passing.

## Next
1. Add scheduling metadata and due-source selection.
2. Add FreeLLMAPI config/export adapter only for gaps not already covered upstream.
3. Add more official sources with provider-specific extractors.
4. Add community discovery, then optional JEV integration.
