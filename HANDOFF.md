# TeleGrabber — AI Agent Handoff File

> **INSTRUCTIONS FOR AI AGENTS:**
> 1. Read this file FIRST before touching any code.
> 2. Check "Current State" and "Active Issue" sections carefully.
> 3. When your session ends (or before context runs out), update this file with what you did and what's next.
> 4. Keep entries brief and factual. No fluff.

---

## 📍 Last Updated

**Date:** 2026-05-13
**Session:** Gemini 3.1 Pro (High) — conversation `c8d98dda-26a7-4c0e-ba62-611c68fe5c8d`

---

## ✅ What Was Completed (Last Session)

- **Media extraction fixed**: `downloader.py` now uploads directly to Supabase Storage bucket (`telegrabber-media`) and deletes the local temp file immediately. No local disk usage.
- **AI categorization fixed**: `categorizer.py` uses `.update()` per row instead of `.upsert()` to avoid NOT NULL constraint violations.
- **Pagination fixed**: `routers/extract.py` — Supabase query now correctly calls `.select()` before `.eq()`.
- **Event loop deadlock fixed**: All Supabase DB and Storage calls in `extractor.py` and `downloader.py` wrapped in `asyncio.to_thread()`.
- **Concurrent media downloads**: `extractor.py` processes media in batched concurrent tasks (up to 10 simultaneous).
- **Google Drive**: Switched from Service Account (0-byte quota error) to OAuth2 `InstalledAppFlow`. `drive.py` uses `google_credentials.json` (OAuth Client ID, Desktop App type). `token.json` is cached after first login.
- **Drive folder naming**: `drive.py` generates intelligent folder names using Gemini API based on export content.
- **Frontend media display**: Dashboard shows real thumbnails/links using full Supabase Storage URLs.
- **ZIP export**: `zip_builder.py` streams media from Supabase Storage URLs (not local disk).

---

## 🔴 Active Issue / Where We Left Off

**Problem**: Extraction shows 0 messages after 5+ minutes on a new job.

**Last debugging steps taken:**
- Confirmed backend is running and Supabase is reachable (Supabase had been auto-paused earlier, was restored)
- The concurrent media batch refactor in `extractor.py` may have introduced a silent error that prevents messages from being committed to DB
- The session ended before the root cause was confirmed

**Suspected location**: `backend/app/telegram/extractor.py` — the message batch commit loop after the concurrent media refactor (around lines 457–490)

**Suggested next step**: Add verbose logging to the extraction loop to see where it stalls. Check if `pending_media_tasks` are blocking the batch commit. Also check if the semaphore is deadlocking.

---

## ⚠️ Known Gotchas (Read Before Coding)

1. **Never call supabase synchronously in async context** — always use `await asyncio.to_thread(lambda: supabase.table(...).execute())`. The `supabase-py` library is synchronous and will deadlock the FastAPI event loop if called directly.
2. **Run backend with `uvicorn app.main:app --port 8000`** — NOT `fastapi dev` or `uvicorn --reload`. Hot-reload during extraction kills background threads and creates zombie jobs.
3. **Google Drive**: `google_credentials.json` must be OAuth Client ID (Desktop App), NOT a Service Account. Service Accounts have 0-byte storage quota on personal Gmail.
4. **Supabase free tier auto-pauses** after inactivity. Restore via dashboard or MCP `restore_project`.
5. **DNS after VPN**: If Supabase throws `getaddrinfo failed`, check Windows DNS settings — VPN may have left static DNS entries.
6. **Media paths**: After the last session's changes, `media_path` in the `messages` table stores full Supabase public URLs (starts with `https://`), NOT local paths.

---

## 🗄️ Infrastructure

| Resource | Value |
|---|---|
| Supabase Project ID | `dkkzpaxuvemxumhmrdzp` |
| Supabase Storage Bucket | `telegrabber-media` (public) |
| Google Drive Credentials | `backend/google_credentials.json` (OAuth2 Client ID) |
| Google Drive Token Cache | `backend/token.json` (auto-generated after first login) |
| Backend Port | `8000` |
| Frontend Port | `3000` |

---

## 📁 Key Files

| File | Purpose |
|---|---|
| `backend/app/telegram/extractor.py` | Main extraction loop — most complex file |
| `backend/app/media/downloader.py` | Telegram download → Supabase Storage upload |
| `backend/app/ai/categorizer.py` | Groq LLM batch categorization |
| `backend/app/export/drive.py` | Google Drive OAuth2 upload |
| `backend/app/routers/extract.py` | REST endpoints for extraction lifecycle |
| `frontend/src/app/dashboard/page.tsx` | Main UI — very large file |
| `backend/.env` | All secrets (never commit) |

---

## 🔮 Pending Features / Nice-to-Haves

- [ ] Fix the 0-messages extraction bug (top priority)
- [ ] Add progress percentage to extraction status
- [ ] Voice note transcription (Whisper stub exists in `transcriber.py`)
- [ ] Multi-job support (currently one active job at a time)
- [ ] Export to NotebookLM directly via API (when Google adds it)
