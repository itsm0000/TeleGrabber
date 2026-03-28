"""
app/ai/formatter.py
────────────────────
Generates a structured export file from categorized messages for NotebookLM ingest.

Markdown output (.md):
  - YAML front-matter (title, source URL, export date, message count)
  - Messages grouped under H2 headings per academic category
  - Each message rendered as a blockquote with sender, date, and text

Plain-text output (.txt):
  - Flat format with [CATEGORY] prefix per message — optimal for
    NotebookLM's plain-text ingestion mode

Output is written to: {export_dir}/{job_id}/export_{job_id}.{ext}
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.config import settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# Human-readable display names for each category label
CATEGORY_DISPLAY: dict[str, str] = {
    "lecture_notes":       "📝 Lecture Notes",
    "past_exam":           "📋 Past Exams",
    "solved_problems":     "✅ Solved Problems",
    "homework_assignment": "📌 Homework & Assignments",
    "textbook_material":   "📚 Textbook Material",
    "summary_cheatsheet":  "⚡ Summaries & Cheat Sheets",
    "subject_media":       "🖼️ Subject Media",
    "other":               "💬 Other",
}

CATEGORY_ORDER = list(CATEGORY_DISPLAY.keys())


def _fetch_messages(job_id: UUID) -> tuple[list[dict], dict]:
    """Return (messages_sorted, job_meta) from Supabase."""
    supabase = get_supabase()

    job_resp = (
        supabase.table("extraction_jobs")
        .select("source_url, created_at")
        .eq("id", str(job_id))
        .maybe_single()
        .execute()
    )
    job_meta = job_resp.data or {}

    msgs_resp = (
        supabase.table("messages")
        .select("message_id, text, sender, date, category, media_path")
        .eq("job_id", str(job_id))
        .order("date", desc=False)
        .execute()
    )
    return msgs_resp.data or [], job_meta


def _group_by_category(messages: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {cat: [] for cat in CATEGORY_ORDER}
    for msg in messages:
        cat = msg.get("category") or "other"
        if cat not in groups:
            cat = "other"
        groups[cat].append(msg)
    return groups


def _render_markdown(job_id: UUID, messages: list[dict], job_meta: dict) -> str:
    source_url = job_meta.get("source_url", "unknown")
    exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    groups = _group_by_category(messages)

    lines: list[str] = [
        "---",
        f"title: TeleGrabber Export — {job_id}",
        f"source: {source_url}",
        f"exported_at: {exported_at}",
        f"total_messages: {len(messages)}",
        "---",
        "",
        f"# TeleGrabber Export",
        f"**Source:** {source_url}  ",
        f"**Exported:** {exported_at}  ",
        f"**Messages:** {len(messages)}",
        "",
    ]

    for cat in CATEGORY_ORDER:
        msgs = groups[cat]
        if not msgs:
            continue
        display = CATEGORY_DISPLAY[cat]
        lines.append(f"## {display}")
        lines.append("")
        for msg in msgs:
            sender = msg.get("sender") or "Unknown"
            date_str = (msg.get("date") or "")[:10]
            text = (msg.get("text") or "").strip()
            media = msg.get("media_path")

            lines.append(f"> **{sender}** · {date_str}")
            if text:
                # Indent multi-line messages inside blockquote
                for line in text.splitlines():
                    lines.append(f"> {line}")
            if media:
                lines.append(f"> 📎 `{os.path.basename(media)}`")
            lines.append(">")
            lines.append("")

    return "\n".join(lines)


def _render_txt(job_id: UUID, messages: list[dict], job_meta: dict) -> str:
    source_url = job_meta.get("source_url", "unknown")
    exported_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    groups = _group_by_category(messages)

    lines: list[str] = [
        f"TeleGrabber Export — {job_id}",
        f"Source: {source_url}",
        f"Exported: {exported_at}",
        f"Total messages: {len(messages)}",
        "=" * 60,
        "",
    ]

    for cat in CATEGORY_ORDER:
        msgs = groups[cat]
        if not msgs:
            continue
        display = CATEGORY_DISPLAY[cat].replace(
            next(iter(CATEGORY_DISPLAY[cat])), "", 1
        ).strip()  # strip emoji for plain text
        lines.append(f"[{cat.upper()}] {display}")
        lines.append("-" * 40)
        for msg in msgs:
            sender = msg.get("sender") or "Unknown"
            date_str = (msg.get("date") or "")[:10]
            text = (msg.get("text") or "").strip()
            media = msg.get("media_path")
            lines.append(f"{sender} ({date_str}):")
            if text:
                lines.append(text)
            if media:
                lines.append(f"[media: {os.path.basename(media)}]")
            lines.append("")
        lines.append("")

    return "\n".join(lines)


def generate_export(job_id: UUID, fmt: str = "markdown") -> tuple[Path, int]:
    """
    Build the export file for a job.

    Returns (file_path, size_in_bytes).
    Raises RuntimeError if the job has no messages.
    """
    messages, job_meta = _fetch_messages(job_id)
    if not messages:
        raise RuntimeError(f"No messages found for job {job_id}.")

    # Ensure output directory exists
    out_dir = Path(settings.export_dir) / str(job_id)
    out_dir.mkdir(parents=True, exist_ok=True)

    if fmt == "markdown":
        content = _render_markdown(job_id, messages, job_meta)
        ext = "md"
    else:
        content = _render_txt(job_id, messages, job_meta)
        ext = "txt"

    out_path = out_dir / f"export_{job_id}.{ext}"
    out_path.write_text(content, encoding="utf-8")

    size = out_path.stat().st_size
    logger.info("Export written: %s (%d bytes)", out_path, size)
    return out_path, size
