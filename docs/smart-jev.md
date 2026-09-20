# Smart v2 + TypeSafe Jev

Smart v2 can use TypeSafe Jev (`jev-latest`) as an optional semantic tie-breaker.
The normal router remains local: rules, multilingual embeddings and NLI run first.
Jev is called only when the local decision is ambiguous, unless explicitly configured otherwise.

## Configuration

Set `TYPESAFE_API_KEY` in the process environment or in `~/.dsh/.env`.
Never commit the key to this repository.

`SMART_JEV_MODE=ambiguity` is the default and recommended mode.
`SMART_JEV_MODE=off` disables all TypeSafe calls.
`SMART_JEV_MODE=always` is intended for diagnostics, not normal use.

## Safety and performance

- Provider timeout: 1.4 seconds.
- Same-request judgments are cached in memory for 5 minutes by prompt hash.
- Two consecutive provider failures open a 60-second circuit breaker.
- Provider failure is fail-open: Smart keeps the local domain/difficulty decision.
- Images are not sent to Jev; only bounded routing text is sent (maximum 3,000 characters).
- High-confidence deterministic rules, explicit Fusion and most simple requests skip Jev.
- Jev complexity is blended only when its Choice confidence is at least 0.75.

## Observability

`/smart/status` exposes Jev health without exposing credentials.
Responses that used Jev include `X-Smart-Jev`, model, confidence and latency headers.
Telemetry records only hashes/decision metadata; it does not add prompt text.
