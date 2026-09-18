from __future__ import annotations

import argparse, json

from .api_schedule import due_api_checks
from .candidate_discovery import import_free_llm_hub
from .catalog_discovery import import_all_catalogs
from .config import DB_PATH
from .db import connect
from .pipeline import scan
from .registration_links import apply_overrides, resolve_for_provider
from .source_registry import load_sources, schedule_status, watch_sources
from .user_actions import (
    build_registration_actions, complete_action, list_pending_actions, registration_plan
)

def main() -> None:
    parser = argparse.ArgumentParser(prog="free-ai-radar")
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser("scan")
    scan_p.add_argument("source", choices=["openrouter"])

    watch_p = sub.add_parser("watch")
    watch_p.add_argument("source", nargs="?", default=None,
                         help="source id, 'all' to force every source, or omit to run only due sources")

    sub.add_parser("sources")
    sub.add_parser("schedule")
    sub.add_parser("api-schedule")
    sub.add_parser("discover-providers")
    sub.add_parser("discover-catalogs")
    sub.add_parser("prepare-actions")
    sub.add_parser("apply-registration-overrides")

    actions_p = sub.add_parser("actions")
    actions_p.add_argument("provider", nargs="?", default=None)

    plan_p = sub.add_parser("registration-plan")
    plan_p.add_argument("--limit", type=int, default=10)

    resolve_p = sub.add_parser("resolve-registration")
    resolve_p.add_argument("provider")

    complete_p = sub.add_parser("complete-action")
    complete_p.add_argument("id", type=int)

    args = parser.parse_args()
    if args.command == "scan":
        result = scan(args.source)
    elif args.command == "watch":
        with connect(DB_PATH) as con:
            result = watch_sources(con, args.source)
    elif args.command == "schedule":
        with connect(DB_PATH) as con:
            result = schedule_status(con)
    elif args.command == "api-schedule":
        with connect(DB_PATH) as con:
            result = due_api_checks(con)
    elif args.command == "discover-providers":
        with connect(DB_PATH) as con:
            result = import_free_llm_hub(con)
    elif args.command == "discover-catalogs":
        with connect(DB_PATH) as con:
            result = import_all_catalogs(con)
    elif args.command == "prepare-actions":
        with connect(DB_PATH) as con:
            result = build_registration_actions(con)
            result["registration_overrides"] = apply_overrides(con)["updated"]
    elif args.command == "apply-registration-overrides":
        with connect(DB_PATH) as con:
            result = apply_overrides(con)
    elif args.command == "actions":
        with connect(DB_PATH) as con:
            result = list_pending_actions(con, args.provider)
    elif args.command == "registration-plan":
        with connect(DB_PATH) as con:
            result = registration_plan(con, args.limit)
    elif args.command == "resolve-registration":
        with connect(DB_PATH) as con:
            result = resolve_for_provider(con, args.provider)
    elif args.command == "complete-action":
        with connect(DB_PATH) as con:
            result = complete_action(con, args.id)
    else:
        result = load_sources()
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
