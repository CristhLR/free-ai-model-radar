from __future__ import annotations

import argparse, json

from .api_schedule import due_api_checks
from .config import DB_PATH
from .db import connect
from .pipeline import scan
from .source_registry import load_sources, schedule_status, watch_sources

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
    else:
        result = load_sources()
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
