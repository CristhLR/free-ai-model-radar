from __future__ import annotations

import argparse, json
from .config import DB_PATH
from .db import connect
from .pipeline import scan
from .source_registry import load_sources, watch_sources

def main() -> None:
    parser = argparse.ArgumentParser(prog="free-ai-radar")
    sub = parser.add_subparsers(dest="command", required=True)
    scan_p = sub.add_parser("scan")
    scan_p.add_argument("source", choices=["openrouter"])

    watch_p = sub.add_parser("watch")
    watch_p.add_argument("source", nargs="?", default="all")
    sub.add_parser("sources")

    args = parser.parse_args()
    if args.command == "scan":
        result = scan(args.source)
    elif args.command == "watch":
        with connect(DB_PATH) as con:
            result = watch_sources(con, None if args.source == "all" else args.source)
    else:
        result = load_sources()
    print(json.dumps(result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
