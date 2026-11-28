#!/usr/bin/env python3
"""Keep a ledger of ESG tender notices and print only unseen records."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from analyze_bids import canon_url, norm_text  # noqa: E402


def record_key(raw: dict) -> str:
    url = canon_url(str(raw.get("url") or ""))
    if url:
        return "u:" + url
    title = norm_text(str(raw.get("title") or ""))
    buyer = norm_text(str(raw.get("buyer") or ""))
    day = str(raw.get("publish_date") or "")
    return "t:" + "|".join((title, buyer, day))


def load_json(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8-sig") as handle:
        return json.load(handle)


def empty_ledger() -> dict:
    return {"version": 1, "items": {}}


def select_new(ledger: dict, incoming: list) -> tuple[list, int]:
    known = ledger.setdefault("items", {})
    fresh = []
    seen_in_batch: set[str] = set()
    for raw in incoming:
        if not isinstance(raw, dict):
            continue
        key = record_key(raw)
        if key in known or key in seen_in_batch:
            continue
        seen_in_batch.add(key)
        fresh.append(raw)
    return fresh, len(incoming) - len(fresh)


def apply_new(ledger: dict, fresh: list, today: str) -> None:
    items = ledger.setdefault("items", {})
    for raw in fresh:
        items[record_key(raw)] = {
            "title": raw.get("title") or "",
            "url": raw.get("url") or "",
            "publish_date": raw.get("publish_date") or "",
            "first_seen": today,
        }


def self_test() -> int:
    ledger = empty_ledger()
    first = [
        {"title": "甲", "url": "https://www.example.com/a?utm_source=1", "publish_date": "2099-01-01"},
        {"title": "乙", "url": "https://example.com/b", "publish_date": "2099-01-02"},
    ]
    fresh, skipped = select_new(ledger, first)
    if len(fresh) != 2 or skipped != 0:
        print("first pass failed", len(fresh), skipped)
        return 1
    apply_new(ledger, fresh, "2099-01-02")
    second = [
        {"title": "甲转载", "url": "https://example.com/a", "publish_date": "2099-01-03"},
        {"title": "丙", "url": "https://example.com/c", "buyer": "某局", "publish_date": "2099-01-03"},
    ]
    fresh, skipped = select_new(ledger, second)
    if len(fresh) != 1 or fresh[0]["title"] != "丙" or skipped != 1:
        print("second pass failed", fresh, skipped)
        return 1
    snapshot = json.dumps(ledger, ensure_ascii=False)
    select_new(ledger, second)
    if json.dumps(ledger, ensure_ascii=False) != snapshot:
        print("dry-run mutated the ledger")
        return 1
    print("OK")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--self-test":
        return self_test()
    parser = argparse.ArgumentParser(description="ESG 招标台账去重")
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--incoming", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--today")
    args = parser.parse_args(argv[1:])
    ledger_path = Path(args.ledger)
    incoming_path = Path(args.incoming)
    try:
        incoming = load_json(incoming_path, [])
        if not isinstance(incoming, list):
            raise ValueError("incoming JSON 必须是数组")
        ledger = load_json(ledger_path, empty_ledger())
        if not isinstance(ledger, dict):
            raise ValueError("台账必须是对象")
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"无法读取：{exc}", file=sys.stderr)
        return 1
    fresh, skipped = select_new(ledger, incoming)
    print(f"新增 {len(fresh)} 条，台账已有或本批重复 {skipped} 条", file=sys.stderr)
    json.dump(fresh, sys.stdout, ensure_ascii=False, indent=2)
    sys.stdout.write("\n")
    if args.apply:
        apply_new(ledger, fresh, args.today or date.today().isoformat())
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("w", encoding="utf-8") as handle:
            json.dump(ledger, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
