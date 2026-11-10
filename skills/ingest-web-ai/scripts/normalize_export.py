#!/usr/bin/env python3
"""normalize_export.py — offline web-AI export → S1-shaped event JSONL (spike).

Design: docs/ingest-web-ai.md. No network, no S1/CAS writes, no credential reads.
Reads one local JSON export (synthetic fixture or operator-supplied dump) and
prints one JSON object per message to stdout or --output.

Exit 0 success, 2 usage / unreadable / invalid input.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Iterator

PRODUCERS = (
    "gemini-web",
    "grok-web",
    "chatgpt-web",
    "claude-web",
    "vesti",
    "unknown-web",
)

# Bound the input read (32 MiB + 1 probe byte) so a huge dump fails closed
# rather than allocating the whole file first.
MAX_INPUT_BYTES = 32 * 1024 * 1024


def _die(msg: str, code: int = 2) -> None:
    print(f"normalize_export: {msg}", file=sys.stderr)
    raise SystemExit(code)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _stable_id(*parts: str) -> str:
    raw = "\0".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def _message_text(msg: dict[str, Any]) -> str:
    for key in ("text", "content", "body", "message"):
        val = msg.get(key)
        if isinstance(val, str):
            return val
        if isinstance(val, list):
            # OpenAI-ish content parts: [{"type":"text","text":"..."}]
            bits: list[str] = []
            for part in val:
                if isinstance(part, str):
                    bits.append(part)
                elif isinstance(part, dict):
                    t = part.get("text")
                    if isinstance(t, str):
                        bits.append(t)
            if bits:
                return "\n".join(bits)
    return ""


def _role(msg: dict[str, Any]) -> str:
    role = msg.get("role") or msg.get("author") or msg.get("sender")
    if isinstance(role, dict):
        role = role.get("role") or role.get("name")
    if not isinstance(role, str) or not role.strip():
        return "unknown"
    role = role.strip().lower()
    if role in ("user", "human", "prompter"):
        return "user"
    if role in ("assistant", "model", "bot", "ai"):
        return "assistant"
    if role in ("system",):
        return "system"
    if role in ("tool", "function"):
        return "tool"
    return "unknown"


def _conversation_fingerprint(messages: list[Any]) -> str:
    """Content fingerprint so untitled/id-less conversations do not collide.

    Hashes role + text for each dict turn (in order). Non-dict items contribute
    an empty slot so index alignment stays stable across sparse lists.
    """
    parts: list[str] = []
    for raw in messages:
        if not isinstance(raw, dict):
            parts.append("")
            continue
        parts.append(f"{_role(raw)}\0{_message_text(raw)}")
    return _sha256_text("\0".join(parts))


def iter_conversations(doc: Any) -> Iterator[dict[str, Any]]:
    """Accept a few export shapes without network schema fetches."""
    if isinstance(doc, list):
        for item in doc:
            if isinstance(item, dict):
                yield item
        return
    if not isinstance(doc, dict):
        _die("export root must be a JSON object or array of conversations")
    for key in ("conversations", "chats", "threads", "items"):
        block = doc.get(key)
        if isinstance(block, list):
            for item in block:
                if isinstance(item, dict):
                    yield item
            return
    # Single conversation document
    if any(k in doc for k in ("messages", "turns", "id", "title")):
        yield doc
        return
    _die("no conversations[] / messages found in export")


def normalize_conversation(
    conv: dict[str, Any],
    *,
    producer: str,
    source_path: str,
    ordinal: int = 0,
) -> list[dict[str, Any]]:
    title = conv.get("title") or conv.get("name") or ""
    if not isinstance(title, str):
        title = ""
    started = conv.get("created_at") or conv.get("started_at") or conv.get("create_time")
    if started is not None and not isinstance(started, str):
        started = str(started)

    messages = None
    for key in ("messages", "turns", "items"):
        if isinstance(conv.get(key), list):
            messages = conv[key]
            break
    if messages is None:
        return []

    # Resolve identity before emitting events. When the export omits id/title/
    # timestamp, include the stable export ordinal and a content fingerprint so
    # sibling conversations in the same file do not share one conversation_id
    # (and therefore collide on message_id = "{conv_id}:{idx}" at the sink).
    conv_id = conv.get("id") or conv.get("conversation_id") or conv.get("uuid")
    if not isinstance(conv_id, str) or not conv_id.strip():
        fingerprint = _conversation_fingerprint(messages)
        conv_id = _stable_id(
            producer,
            title,
            started or "",
            source_path,
            str(ordinal),
            fingerprint,
        )

    events: list[dict[str, Any]] = []
    for idx, raw in enumerate(messages):
        if not isinstance(raw, dict):
            continue
        text = _message_text(raw)
        msg_id = raw.get("id") or raw.get("message_id") or raw.get("uuid")
        if not isinstance(msg_id, str) or not msg_id.strip():
            msg_id = f"{conv_id}:{idx}"
        ts = raw.get("ts") or raw.get("timestamp") or raw.get("created_at") or raw.get("create_time")
        if ts is not None and not isinstance(ts, str):
            ts = str(ts)
        event: dict[str, Any] = {
            "schema": "ade.web-ai.event.v0",
            "producer": producer,
            "conversation_id": conv_id,
            "message_id": msg_id,
            "role": _role(raw),
            "text": text,
            "source_path": source_path,
            "content_sha256": _sha256_text(text),
        }
        if ts:
            event["ts"] = ts
        if title:
            event["conversation_title"] = title
        events.append(event)
    return events


def normalize_document(
    doc: Any,
    *,
    producer: str,
    source_path: str,
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for ordinal, conv in enumerate(iter_conversations(doc)):
        out.extend(
            normalize_conversation(
                conv,
                producer=producer,
                source_path=source_path,
                ordinal=ordinal,
            )
        )
    return out


def read_bounded(path: Path, *, limit: int = MAX_INPUT_BYTES) -> bytes:
    """Read at most ``limit + 1`` bytes; refuse when the file exceeds ``limit``."""
    try:
        with path.open("rb") as fh:
            data = fh.read(limit + 1)
    except OSError as exc:
        _die(f"cannot read {path}: {exc.__class__.__name__}")
    if len(data) > limit:
        _die(f"input larger than {limit} bytes; refuse")
    return data


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Normalize a local web-AI export JSON into S1-shaped event JSONL "
        "(no network; docs/ingest-web-ai.md)."
    )
    p.add_argument("--input", "-i", required=True, help="Path to a local export JSON file")
    p.add_argument(
        "--producer",
        "-p",
        default="unknown-web",
        choices=PRODUCERS,
        help="Producer id for the envelope (default: unknown-web)",
    )
    p.add_argument(
        "--output",
        "-o",
        help="Write JSONL here (default: stdout). Parent dirs must already exist.",
    )
    args = p.parse_args(argv)

    path = Path(args.input)
    if not path.is_file():
        _die(f"input is not a file: {path}")
    data = read_bounded(path)
    try:
        doc = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        _die(f"invalid JSON in {path}: {exc}")

    events = normalize_document(doc, producer=args.producer, source_path=str(path))
    lines = [json.dumps(ev, ensure_ascii=False, sort_keys=True) for ev in events]
    body = ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")

    if args.output:
        out = Path(args.output)
        try:
            # Atomic replace beside the target (review rule 6).
            tmp = out.with_name(out.name + ".tmp")
            tmp.write_bytes(body)
            tmp.replace(out)
        except OSError as exc:
            _die(f"cannot write {out}: {exc.__class__.__name__}")
    else:
        sys.stdout.buffer.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
