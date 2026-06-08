"""
app/ai/categorizer.py
─────────────────────
Gemini-powered message categorizer for university academic content.

Uses gemini-2.0-flash to batch-tag stored Telegram messages with one of 8
academic labels, then upserts the category back into the Supabase messages table.

Category taxonomy:
  lecture_notes      – slides, handwritten notes, typed summaries
  past_exam          – final exams, midterms, quizzes (solved or not)
  solved_problems    – worked solutions, example sheets
  homework_assignment – raw homework / assignment / lab files
  textbook_material  – PDF chapters, official reference material
  summary_cheatsheet – formula sheets, revision cards, cheat sheets
  subject_media      – diagrams, images, figures, infographics
  other              – off-topic, discussion text, links, unclassifiable
"""
from __future__ import annotations

import json
import logging
from uuid import UUID


import httpx

from app.config import settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

BATCH_SIZE = 50  # Gemini context window is generous; 50 msgs is safe

SYSTEM_PROMPT = """You are an academic content classifier for university study material.
You will receive a JSON array of Telegram messages (id + text).
Classify each one into EXACTLY ONE of these labels:
  - lecture_notes      : typed/scanned lecture slides, handwritten notes, class summaries
  - past_exam          : final exams, midterms, quizzes — solved OR unsolved
  - solved_problems    : worked solutions, solved exercises, example answer sheets
  - homework_assignment: raw homework sheets, assignments, lab tasks (NOT yet solved)
  - textbook_material  : textbook PDF chapters, official course material excerpts
  - summary_cheatsheet : formula sheets, revision notes, cheat sheets, quick-reference cards
  - subject_media      : images, diagrams, figures, infographics related to the subject
  - other              : off-topic chat, links without content, unclassifiable text

Rules:
- If the message has no text but has media mentioned, lean toward subject_media or other.
- Respond with ONLY a valid JSON object mapping each message id to its label.
  Example: {"123": "lecture_notes", "124": "past_exam"}
- Do NOT include any explanation or markdown fences."""


def _build_prompt(messages: list[dict]) -> str:
    items = [
        {"id": str(m["message_id"]), "text": (m.get("text") or "")[:500]}
        for m in messages
    ]
    return f"Classify these messages:\n{json.dumps(items, ensure_ascii=False)}"


def _parse_response(raw: str) -> dict[str, str]:
    """Extract the JSON mapping from the response, stripping any markdown fences."""
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


async def categorize_job(job_id: UUID) -> int:
    """
    Fetch all uncategorized messages for `job_id`, call Groq in batches,
    and upsert the category column back to Supabase.

    Returns the total number of messages categorized in this run.
    """
    if not settings.groq_api_key:
        raise RuntimeError("GROQ_API_KEY is not configured.")

    supabase = get_supabase()

    # Fetch messages that haven't been categorized yet
    resp = (
        supabase.table("messages")
        .select("id, message_id, text")
        .eq("job_id", str(job_id))
        .is_("category", "null")
        .execute()
    )
    rows: list[dict] = resp.data or []
    if not rows:
        logger.info("No uncategorized messages for job %s", job_id)
        return 0

    total_categorized = 0
    groq_url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {settings.groq_api_key}",
        "Content-Type": "application/json"
    }

    # Process in batches of BATCH_SIZE
    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        prompt = _build_prompt(batch)

        try:
            payload = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                "response_format": {"type": "json_object"}
            }
            # Need to use httpx synchronously or async. Since categorize_job is async, let's use httpx.AsyncClient
            async with httpx.AsyncClient() as client:
                res = await client.post(groq_url, headers=headers, json=payload, timeout=60.0)
                res.raise_for_status()
                data = res.json()
                raw_text = data["choices"][0]["message"]["content"]
                mapping: dict[str, str] = _parse_response(raw_text)
        except Exception as e:
            logger.exception("Groq categorization failed for batch starting at %d. Error: %s", i, e)
            if 'raw_text' in locals():
                logger.error("Raw text was: %s", raw_text)
            continue

        # Update each row individually to avoid NOT NULL constraint errors during upsert
        for row in batch:
            cat = mapping.get(str(row["message_id"]), "other")
            supabase.table("messages").update({"category": cat}).eq("id", row["id"]).execute()
            
        total_categorized += len(batch)
        logger.info(
            "Job %s: categorized messages %d–%d", job_id, i, i + len(batch) - 1
        )

    return total_categorized
