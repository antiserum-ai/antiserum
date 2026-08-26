from __future__ import annotations

import argparse
import sys
from pathlib import Path

from antiserum import __version__
from antiserum.errors import AntiserumError
from antiserum.feed import resolve_feed
from antiserum.receipt import dumps, format_text, write_json
from antiserum.scan import scan


def entry() -> None:
    sys.exit(main())


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except AntiserumError as exc:
        print(f"antiserum: {exc}", file=sys.stderr)
        return 2


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="antiserum",
        description="Antivirus for training data. Scan a local text dataset for poison.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan_p = sub.add_parser(
        "scan",
        help="scan a folder or file of text records",
        description=(
            "Ingest .jsonl (objects with a text field) and .txt files, "
            "run local poison checks, and print a receipt."
        ),
    )
    scan_p.add_argument(
        "path",
        type=Path,
        help="folder of records, or a single .jsonl / .txt file",
    )
    scan_p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the JSON receipt to this file",
    )
    scan_p.add_argument(
        "--feed",
        type=Path,
        default=None,
        help="signature feed JSONL (default: feed/signatures.jsonl walking up from cwd)",
    )
    scan_p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print the JSON receipt instead of the text summary",
    )
    scan_p.set_defaults(func=_cmd_scan)
    return parser


def _cmd_scan(args: argparse.Namespace) -> int:
    feed = resolve_feed(args.feed)
    if args.feed is not None and not Path(args.feed).exists():
        raise AntiserumError(f"signature feed not found: {args.feed}")
    receipt = scan(args.path, feed_path=feed)
    if args.as_json:
        sys.stdout.write(dumps(receipt) + "\n")
    else:
        sys.stdout.write(format_text(receipt))
    if args.out is not None:
        write_json(receipt, args.out)
        if not args.as_json:
            sys.stdout.write(f"\nwrote {args.out}\n")
    return 0
