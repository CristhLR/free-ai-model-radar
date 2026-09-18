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
- 9 unit tests passing.

## Verified behavior
- Immediately after a full run, a normal due-only run returns [] and performs no unnecessary source checks.
- Scheduled task manual run returned exit code 0.
- JEV has not been used.

## Next
1. Add provider-specific extractors that turn changed docs into structured facts (free tier, quotas, expiry/deprecation).
2. Add confidence/evidence scoring and candidate lifecycle gates.
3. Add FreeLLMAPI declarative-config exporter for verified gaps only.
4. Add community discovery feeds; keep them discovery-only until official verification.
5. Add optional JEV for ambiguous/new-provider research after the cheap pipeline filters candidates.
