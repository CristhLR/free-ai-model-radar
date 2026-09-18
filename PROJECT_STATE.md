# Project state

## Goal
Discover and validate changing free AI API models, then feed useful verified changes into FreeLLMAPI for DeepSeek Harness.

## Decisions
- FreeLLMAPI handles routing, quotas, fallback, unified /v1 and DSH setup.
- Radar owns discovery, evidence, scheduling, validation history and change detection.
- Python stdlib first; avoid dependencies until needed.
- FREE_ONLY is the hard default.
- JEV remains disabled unless explicitly authorized.

## Working now
- OpenRouter official free-model scan with NEW / CHANGED / REMOVED diff.
- SQLite model/event/source/API-check state with migrations.
- 22 official monitoring signals across FreeLLMAPI, OpenRouter, Groq, Google, Cloudflare, Cohere, Hugging Face, Cerebras and NVIDIA.
- Conditional HTTP with ETag / Last-Modified plus normalized HTML fingerprints.
- Adaptive cadence: stable sources back off from hours toward days/weeks; changed sources reset to faster checks.
- expected_change_at / next_check_at support.
- Expensive API checks can be deferred until a known change/preflight window.
- Bounded concurrency (6 workers); full 22-source validation completed in ~9 seconds with zero source failures.
- Windows task FreeAIModelRadar runs hourly; internal scheduler skips non-due sources.
- 13 unit tests passing.
- Five discovery catalogs integrated: free-llm-api-hub, free-ai-api-tiers, free-llm-services, awesome-freellm-apis, and DaBinBinah/free-LLM (China-focused replacement for the dead cheahjs source).
- Catalog evidence is stored separately; secondary sources fill missing fields but never overwrite known values. Conflicts are recorded for later official verification.
- Current real import: 166 catalog records -> 99 unique provider candidates, zero exact-name duplicates, 13 flagged conflicts.
- Registration queue and curated registration-link overrides are working.

## Verified behavior
- Immediately after a full run, a normal due-only run returns [] and performs no unnecessary source checks.
- Scheduled task manual run returned exit code 0.
- JEV has not been used.

## Next
1. Present only the highest-value registration actions to the user and collect provider keys locally.
2. Validate each obtained key/model with a cheap health check before activation.
3. Export verified active providers into FreeLLMAPI and point DeepSeek Harness at its single /v1 endpoint.
4. Keep JEV optional and disabled until explicitly authorized; use it only for ambiguous cases after deterministic filtering.
