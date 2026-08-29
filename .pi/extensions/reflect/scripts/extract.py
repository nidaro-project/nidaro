#!/usr/bin/env python3
"""Extract a compact view of a pi session log for retrospective review.

Reads a pi session JSONL file (session format v3) and prints JSON with the
conversation arc, tool call counts, tool result sizes, skill reads, subagent
dispatches, errors, and token totals. Stdlib only. Streams line by line and
never holds the whole file in memory.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime

SCHEMA_VERSION = 1
ARC_BLOCK_LIMIT = 2000
PREVIEW_LIMIT = 300

USAGE_KEYS = ("input", "output", "cacheRead", "cacheWrite", "reasoning", "totalTokens")
SKILL_PATH_RE = re.compile(r"skills/([^/]+)/SKILL\.md$")
BIG_STOP_REASONS = ("error", "aborted", "length")


def parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def block_text(content):
    """Concatenate text across content blocks; accept a plain string."""
    if isinstance(content, str):
        return content
    parts = []
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                text = block.get("text")
                if isinstance(text, str):
                    parts.append(text)
    return "\n".join(part for part in parts if part)


def truncate(text, limit):
    if len(text) <= limit:
        return text
    dropped = len(text) - limit
    return text[:limit] + f" ...[truncated {dropped} chars]"


def skill_name(path):
    if not path:
        return None
    normalized = path.replace(os.sep, "/")
    match = SKILL_PATH_RE.search(normalized)
    if match:
        return match.group(1)
    # Root markdown skill files live directly inside a skills/ directory.
    if "/skills/" in normalized:
        parent = os.path.basename(os.path.dirname(normalized))
        base = os.path.basename(normalized)
        if parent == "skills" and base.endswith(".md"):
            return base[:-3]
    return None


class Extractor:
    """Walks session entries and accumulates the extraction output."""

    def __init__(self, max_block: int):
        self.max_block = max_block
        self.header: dict = {}
        self.first_ts = None
        self.last_ts = None
        self.entry_types: Counter = Counter()
        self.turns = 0
        self.assistant_messages = 0
        self.tool_calls = 0
        self.usage_totals: dict[str, int] = {}
        self.cost_total = 0.0
        self.models: set[str] = set()
        self.stop_reasons: Counter = Counter()
        self.tools: dict[str, dict] = {}
        self.skills: list[dict] = []
        self.subagents: list[dict] = []
        self.errors: list[dict] = []
        self.compactions = 0
        self.arc: list[dict] = []

    def feed(self, entry: dict):
        self.entry_types[entry.get("type", "unknown")] += 1
        ts = parse_ts(entry.get("timestamp"))
        if ts:
            if self.first_ts is None:
                self.first_ts = ts
            self.last_ts = ts

        etype = entry.get("type")
        if etype == "session":
            self.header = entry
        elif etype == "compaction":
            self.compactions += 1
        elif etype == "message":
            self.message(entry)

    def message(self, entry: dict):
        role = (entry.get("message") or {}).get("role")
        entry_id = entry.get("id", "")
        if role == "user":
            self.user(entry, entry_id)
        elif role == "assistant":
            self.assistant(entry, entry_id)
        elif role == "toolResult":
            self.tool_result(entry, entry_id)
        elif role == "bashExecution":
            self.bash(entry, entry_id)

    def user(self, entry: dict, entry_id: str):
        self.turns += 1
        text = block_text(entry["message"].get("content"))
        if text:
            self.arc.append(
                {"id": entry_id, "role": "user", "text": truncate(text, self.max_block)}
            )

    def assistant(self, entry: dict, entry_id: str):
        message = entry["message"]
        self.assistant_messages += 1
        self.account_usage(message)
        called = self.tool_calls_of(message, entry_id)
        row: dict[str, object] = {
            "id": entry_id,
            "role": "assistant",
            "text": truncate(block_text(message.get("content")), self.max_block),
        }
        if called:
            row["tools"] = called
        stop = message.get("stopReason")
        if stop:
            self.stop_reasons[stop] += 1
            if stop in BIG_STOP_REASONS:
                row["stop"] = stop
        self.arc.append(row)

    def account_usage(self, message: dict):
        usage = message.get("usage") or {}
        for key in USAGE_KEYS:
            value = usage.get(key)
            if isinstance(value, (int, float)):
                self.usage_totals[key] = self.usage_totals.get(key, 0) + int(value)
        cost = usage.get("cost")
        if isinstance(cost, dict) and isinstance(cost.get("total"), (int, float)):
            self.cost_total += cost["total"]
        provider = message.get("provider")
        model = message.get("model")
        if provider and model:
            self.models.add(f"{provider}/{model}")

    def tool_calls_of(self, message: dict, entry_id: str) -> list[str]:
        called = []
        for block in message.get("content") or []:
            if not isinstance(block, dict) or block.get("type") != "toolCall":
                continue
            self.tool_calls += 1
            name = block.get("name", "?")
            stats = self.tools.setdefault(
                name,
                {
                    "calls": 0,
                    "errors": 0,
                    "result_total_bytes": 0,
                    "result_max_bytes": 0,
                },
            )
            stats["calls"] += 1
            called.append(name)
            if name == "read":
                self.record_skill(block, entry_id)
            elif name in ("subagent_spawn", "workflow"):
                self.record_subagent(block, entry_id)
        return called

    def record_skill(self, call: dict, entry_id: str):
        path = (call.get("arguments") or {}).get("path")
        name = skill_name(path)
        if name:
            self.skills.append({"name": name, "path": path, "entry_id": entry_id})

    def record_subagent(self, call: dict, entry_id: str):
        args = call.get("arguments") or {}
        self.subagents.append(
            {
                "tool": call.get("name", "?"),
                "name": args.get("name"),
                "prompt_preview": truncate(str(args.get("prompt", "")), PREVIEW_LIMIT),
                "entry_id": entry_id,
            }
        )

    def tool_result(self, entry: dict, entry_id: str):
        message = entry["message"]
        name = message.get("toolName", "?")
        stats = self.tools.setdefault(
            name,
            {"calls": 0, "errors": 0, "result_total_bytes": 0, "result_max_bytes": 0},
        )
        size = len(block_text(message.get("content")))
        stats["result_total_bytes"] += size
        stats["result_max_bytes"] = max(stats["result_max_bytes"], size)
        if message.get("isError"):
            stats["errors"] += 1
            self.errors.append(
                {
                    "entry_id": entry_id,
                    "tool": name,
                    "preview": truncate(block_text(message.get("content")), PREVIEW_LIMIT),
                }
            )

    def bash(self, entry: dict, entry_id: str):
        message = entry["message"]
        self.arc.append(
            {
                "id": entry_id,
                "role": "bash",
                "text": truncate(
                    f"$ {message.get('command', '')}\nexit={message.get('exitCode')}",
                    self.max_block,
                ),
            }
        )

    def result(self) -> dict:
        for stats in self.tools.values():
            calls = stats["calls"] or 1
            stats["result_avg_bytes"] = stats["result_total_bytes"] // calls
        duration = None
        if self.first_ts and self.last_ts:
            duration = round((self.last_ts - self.first_ts).total_seconds())
        return {
            "schema_version": SCHEMA_VERSION,
            "session": {
                "file": "",
                "id": self.header.get("id"),
                "cwd": self.header.get("cwd"),
                "parent_session": self.header.get("parentSession"),
                "started": self.header.get("timestamp"),
                "duration_seconds": duration,
            },
            "totals": {
                "user_turns": self.turns,
                "assistant_messages": self.assistant_messages,
                "tool_calls": self.tool_calls,
                "tokens": dict(self.usage_totals),
                "cost_total": round(self.cost_total, 4),
                "models": sorted(self.models),
                "compactions": self.compactions,
                "stop_reasons": dict(self.stop_reasons),
                "entry_types": dict(self.entry_types),
            },
            "tools": dict(sorted(self.tools.items())),
            "skills": self.skills,
            "subagents": self.subagents,
            "errors": self.errors,
            "arc": self.arc,
        }


def extract(path, max_block):
    extractor = Extractor(max_block)
    with open(path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                extractor.entry_types["unparsable"] += 1
                continue
            extractor.feed(entry)
    out = extractor.result()
    out["session"]["file"] = os.path.abspath(path)
    return out


def extract_metadata(path):
    """Head/tail scan only, for verifying a log is the session you think it is."""
    size = os.path.getsize(path)
    with open(path, "rb") as handle:
        head = handle.read(65536).decode("utf-8", errors="replace")
        handle.seek(max(0, size - 65536))
        tail = handle.read().decode("utf-8", errors="replace")

    header: dict = {}
    first_user = None
    for line in head.split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        if entry.get("type") == "session" and not header:
            header = entry
        elif (
            entry.get("type") == "message"
            and (entry.get("message") or {}).get("role") == "user"
            and first_user is None
        ):
            first_user = truncate(block_text(entry["message"].get("content")), 120)

    last_entry = None
    for line in reversed(tail.split("\n")):
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue
        last_entry = entry.get("timestamp")
        break

    return {
        "file": os.path.abspath(path),
        "size_bytes": size,
        "session_id": header.get("id"),
        "cwd": header.get("cwd"),
        "started": header.get("timestamp"),
        "last_entry": last_entry,
        "first_user_prompt": first_user,
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_log", help="path to a pi session .jsonl file")
    parser.add_argument(
        "--metadata-only",
        action="store_true",
        help="print session identity from head/tail only, no full parse",
    )
    parser.add_argument(
        "--max-block",
        type=int,
        default=ARC_BLOCK_LIMIT,
        help="per-block truncation limit for arc text (default %(default)s)",
    )
    args = parser.parse_args(argv)

    if args.metadata_only:
        out = extract_metadata(args.session_log)
    else:
        out = extract(args.session_log, args.max_block)
    json.dump(out, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
