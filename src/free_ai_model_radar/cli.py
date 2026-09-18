from __future__ import annotations

import argparse, json
from .pipeline import scan

def main() -> None:
    parser = argparse.ArgumentParser(prog="free-ai-radar")
    sub = parser.add_subparsers(dest="command", required=True)
    scan_p = sub.add_parser("scan")
    scan_p.add_argument("source", choices=["openrouter"])
    args = parser.parse_args()
    if args.command == "scan":
        print(json.dumps(scan(args.source), indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
