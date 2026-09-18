# Agent rules

- Keep this file short. Read PROJECT_STATE.md before work.
- FreeLLMAPI is the router; this project is the discovery/validation layer.
- Never expose, log, commit, or overwrite secrets.
- JEV is disabled unless the user explicitly authorizes its use.
- Prefer official APIs/docs; community sources only discover candidates.
- Work incrementally: search before reading large files; report diffs, not full state.
- FREE_ONLY is a hard safety rule: unknown or paid routes never become active free routes.
