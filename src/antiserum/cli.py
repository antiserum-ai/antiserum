from __future__ import annotations

import argparse
import sys
from pathlib import Path

from antiserum import __version__
from antiserum.confirm import settle
from antiserum.errors import AntiserumError
from antiserum.feed import resolve_feed
from antiserum.ingest import ingest
from antiserum.judge import first_pass
from antiserum.judgments import FINAL_DECISIONS, format_text as format_judgments
from antiserum.judgments import load as load_judgments
from antiserum.judgments import write_json, write_jsonl
from antiserum.propose import apply_to_feed, collect_proposals, format_lines, format_patch, format_pr_body
from antiserum.receipt import dumps, format_text, load_json, write_json as write_receipt
from antiserum.scan import DEFAULT_FAIL_ON, FAIL_ON_CHOICES, scan, scan_exit_code
from antiserum.signatures import MATCH_TYPES, load_signatures

EXIT_CODE_HELP = (
    "Exit codes:\n"
    "  0  ran; no flags at or above the --fail-on threshold\n"
    "  1  one or more flags at or above the --fail-on threshold\n"
    "  2  usage or I/O error\n"
    "\n"
    "scan --fail-on {any,high,never} sets the threshold (default: never). "
    "Other commands exit 0 on success or 2 on usage/I/O error. "
    "Receipt JSON flags[].severity is enough to fail a job without scraping text."
)


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
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=(
            "Antivirus for training data. Scan a local text dataset, "
            "judge flags against a published rubric, and propose signatures."
        ),
        epilog=EXIT_CODE_HELP,
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    _add_scan(sub)
    _add_judge(sub)
    _add_confirm(sub)
    _add_propose(sub)
    return parser


def _add_scan(sub: argparse._SubParsersAction) -> None:
    scan_p = sub.add_parser(
        "scan",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        help="scan a folder or file of text records",
        description=(
            "Ingest .jsonl (text, Alpaca, messages, or prompt+completion) "
            "and .txt files, run local poison checks, and print a receipt."
        ),
        epilog=EXIT_CODE_HELP,
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
        "--allowlist",
        type=Path,
        default=None,
        help=(
            "local allowlist JSONL of record id, normalized sha256, or "
            "signature id (default: allowlist.jsonl next to the dataset "
            "or at the repo root)"
        ),
    )
    scan_p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print the JSON receipt instead of the text summary",
    )
    scan_p.add_argument(
        "--fail-on",
        choices=FAIL_ON_CHOICES,
        default=DEFAULT_FAIL_ON,
        dest="fail_on",
        help=(
            "exit 1 when flags meet this severity: any flag, high only, "
            "or never (default: never)"
        ),
    )
    scan_p.set_defaults(func=_cmd_scan)


def _add_judge(sub: argparse._SubParsersAction) -> None:
    judge_p = sub.add_parser(
        "judge",
        help="offline first-pass over a scan receipt",
        description=(
            "Read a scan receipt and the source folder, apply the published "
            "confirm rubric, and write a judgments file. Works offline. "
            "No API key. Optional ANTISERUM_JUDGE_HOOK=module:function "
            "falls back to the heuristic if unset or if the hook fails."
        ),
    )
    judge_p.add_argument(
        "path",
        type=Path,
        help="same folder or file that was scanned",
    )
    judge_p.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="JSON receipt from antiserum scan --out (scans first if omitted)",
    )
    judge_p.add_argument(
        "--out",
        type=Path,
        default=Path("judgments.json"),
        help="write judgments JSON here (default: judgments.json)",
    )
    judge_p.add_argument(
        "--jsonl",
        action="store_true",
        help="write judgments as JSONL instead of a JSON document",
    )
    judge_p.add_argument(
        "--feed",
        type=Path,
        default=None,
        help="signature feed used if a receipt is not supplied",
    )
    judge_p.add_argument(
        "--json",
        action="store_true",
        dest="as_json",
        help="print the judgments JSON instead of the text summary",
    )
    judge_p.set_defaults(func=_cmd_judge)


def _add_confirm(sub: argparse._SubParsersAction) -> None:
    confirm_p = sub.add_parser(
        "confirm",
        help="settle a leftover flag as poison, junk, or false_alarm",
        description=(
            "Override or fill a needs_human row in a judgments file. "
            "Without --flag/--decision, lists leftovers. On a TTY, prompts "
            "for one decision. Edit the JSON by hand if you prefer."
        ),
    )
    confirm_p.add_argument(
        "--judgments",
        type=Path,
        required=True,
        help="judgments JSON/JSONL from antiserum judge",
    )
    confirm_p.add_argument(
        "--flag",
        default=None,
        help="flag id to settle, e.g. label_flips:p-flip-1",
    )
    confirm_p.add_argument(
        "--decision",
        choices=FINAL_DECISIONS,
        default=None,
        help="poison, junk, or false_alarm",
    )
    confirm_p.add_argument(
        "--rationale",
        default=None,
        help="why this decision (required when --decision is set)",
    )
    confirm_p.add_argument(
        "--path",
        type=Path,
        default=None,
        help="source folder, used to draft a signature for poison",
    )
    confirm_p.add_argument(
        "--receipt",
        type=Path,
        default=None,
        help="original receipt, used to recover flag evidence",
    )
    confirm_p.add_argument(
        "--pattern",
        default=None,
        help="signature pattern to attach when decision is poison",
    )
    confirm_p.add_argument(
        "--match",
        choices=MATCH_TYPES,
        default="literal",
        help="signature match type when --pattern is set (default: literal)",
    )
    confirm_p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the updated judgments here (default: overwrite --judgments)",
    )
    confirm_p.set_defaults(func=_cmd_confirm)


def _add_propose(sub: argparse._SubParsersAction) -> None:
    propose_p = sub.add_parser(
        "propose",
        help="turn poison judgments into signature lines and a PR body",
        description=(
            "For each poison judgment with a specific pattern, emit the next "
            "AS-YYYY-NNNN line and a pull-request body. Nothing is hosted."
        ),
    )
    propose_p.add_argument(
        "--judgments",
        type=Path,
        required=True,
        help="judgments JSON/JSONL",
    )
    propose_p.add_argument(
        "--feed",
        type=Path,
        default=None,
        help="existing feed, used to pick the next id and skip duplicates",
    )
    propose_p.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write new signature JSONL lines to this file",
    )
    propose_p.add_argument(
        "--pr-body",
        type=Path,
        default=None,
        dest="pr_body",
        help="write the PR body template to this file",
    )
    propose_p.add_argument(
        "--patch",
        type=Path,
        default=None,
        help="write a unified diff against the feed (use - for stdout only via default print)",
    )
    propose_p.add_argument(
        "--apply",
        action="store_true",
        help="append the new lines to the feed file",
    )
    propose_p.set_defaults(func=_cmd_propose)


def _cmd_scan(args: argparse.Namespace) -> int:
    feed = _feed_or_error(args.feed)
    receipt = scan(args.path, feed_path=feed, allowlist_path=args.allowlist)
    if args.as_json:
        sys.stdout.write(dumps(receipt) + "\n")
    else:
        sys.stdout.write(format_text(receipt))
    if args.out is not None:
        write_receipt(receipt, args.out)
        if not args.as_json:
            sys.stdout.write(f"\nwrote {args.out}\n")
    return scan_exit_code(receipt, args.fail_on)


def _cmd_judge(args: argparse.Namespace) -> int:
    records, dataset_hash = ingest(args.path)
    if args.receipt is not None:
        receipt = load_json(args.receipt)
        if receipt.dataset_hash and receipt.dataset_hash != dataset_hash:
            raise AntiserumError(
                f"receipt dataset_hash {receipt.dataset_hash} does not match "
                f"{args.path} ({dataset_hash})"
            )
    else:
        feed = _feed_or_error(args.feed)
        receipt = scan(args.path, feed_path=feed)
    store = first_pass(receipt, records)
    store.path = str(args.path)
    store.receipt = str(args.receipt) if args.receipt is not None else None
    store.dataset_hash = dataset_hash
    if args.jsonl:
        write_jsonl(store, args.out)
    else:
        write_json(store, args.out)
    if args.as_json:
        from antiserum.judgments import dumps as dumps_judgments

        sys.stdout.write(dumps_judgments(store) + "\n")
    else:
        sys.stdout.write(format_judgments(store))
        sys.stdout.write(f"\nwrote {args.out}\n")
    return 0


def _cmd_confirm(args: argparse.Namespace) -> int:
    store = load_judgments(args.judgments)
    if args.flag is None and args.decision is None:
        leftovers = store.leftovers()
        if not leftovers:
            sys.stdout.write("no leftovers. every flag already has a final decision.\n")
            return 0
        sys.stdout.write(f"needs_human: {len(leftovers)}\n")
        for judgment in leftovers:
            sys.stdout.write(f"  {judgment.flag_id}  {judgment.rationale}\n")
        if sys.stdin.isatty():
            return _prompt_settle(store, args, leftovers[0].flag_id)
        sys.stdout.write(
            "\nsettle one with:\n"
            f"  antiserum confirm --judgments {args.judgments} "
            f"--flag {leftovers[0].flag_id} "
            "--decision poison|junk|false_alarm --rationale '...'\n"
        )
        return 0
    if args.flag is None or args.decision is None or not args.rationale:
        raise AntiserumError(
            "confirm a row with --flag, --decision, and --rationale "
            "(or run without them to list leftovers)"
        )
    records = ingest(args.path)[0] if args.path is not None else None
    flags = load_json(args.receipt).flags if args.receipt is not None else None
    updated = settle(
        store,
        flag_key=args.flag,
        decision=args.decision,
        rationale=args.rationale,
        records=records,
        flags=flags,
        pattern=args.pattern,
        match=args.match,
    )
    dest = args.out or args.judgments
    write_json(store, dest)
    sys.stdout.write(
        f"{updated.flag_id}  {updated.decision}  {updated.judge}  {updated.rationale}\n"
    )
    if updated.proposed_signature:
        sys.stdout.write(
            f"  proposed {updated.proposed_signature.get('match')} "
            f"{updated.proposed_signature.get('pattern')!r}\n"
        )
    sys.stdout.write(f"wrote {dest}\n")
    return 0


def _prompt_settle(store, args: argparse.Namespace, default_flag: str) -> int:
    flag_key = input(f"flag id [{default_flag}]: ").strip() or default_flag
    decision = input("decision [poison/junk/false_alarm]: ").strip()
    rationale = input("rationale: ").strip()
    records = ingest(args.path)[0] if args.path is not None else None
    flags = load_json(args.receipt).flags if args.receipt is not None else None
    updated = settle(
        store,
        flag_key=flag_key,
        decision=decision,
        rationale=rationale,
        records=records,
        flags=flags,
        pattern=args.pattern,
        match=args.match,
    )
    dest = args.out or args.judgments
    write_json(store, dest)
    sys.stdout.write(f"{updated.flag_id}  {updated.decision}\nwrote {dest}\n")
    return 0


def _cmd_propose(args: argparse.Namespace) -> int:
    store = load_judgments(args.judgments)
    feed_path = _feed_or_error(args.feed)
    existing: list[dict] = []
    if feed_path is not None and feed_path.exists():
        existing = load_signatures(feed_path)
    elif args.feed is not None:
        raise AntiserumError(f"signature feed not found: {args.feed}")
    signatures = collect_proposals(store, feed=existing)
    body = format_pr_body(signatures, store)
    if signatures:
        sys.stdout.write(format_lines(signatures))
        sys.stdout.write("\n")
    sys.stdout.write(body)
    if args.out is not None:
        args.out.write_text(format_lines(signatures), encoding="utf-8")
        sys.stdout.write(f"\nwrote {args.out}\n")
    if args.pr_body is not None:
        args.pr_body.write_text(body, encoding="utf-8")
        sys.stdout.write(f"wrote {args.pr_body}\n")
    if args.patch is not None:
        if feed_path is None:
            raise AntiserumError("need a feed path to write a patch (pass --feed)")
        patch = format_patch(feed_path, signatures)
        if str(args.patch) == "-":
            sys.stdout.write(patch)
        else:
            args.patch.write_text(patch, encoding="utf-8")
            sys.stdout.write(f"wrote {args.patch}\n")
    if args.apply:
        if feed_path is None:
            raise AntiserumError("need a feed path to apply (pass --feed)")
        apply_to_feed(feed_path, signatures)
        sys.stdout.write(f"appended {len(signatures)} line(s) to {feed_path}\n")
    return 0


def _feed_or_error(explicit: Path | None) -> Path | None:
    feed = resolve_feed(explicit)
    if explicit is not None and not Path(explicit).exists():
        raise AntiserumError(f"signature feed not found: {explicit}")
    return feed
