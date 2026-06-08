# TeleGrabber 📡

> High-speed Telegram extraction, categorization & management tool — authenticated via MTProto user client, powered by Supabase and Gemini AI, optimized for Google NotebookLM ingest.

---

## Table of Contents

- [What This Is](#what-this-is)
- [Architecture Overview](#architecture-overview)
- [Supabase Schema](#supabase-schema)
- [Quick Start](#quick-start)
- [Running the Application](#running-the-application)
- [API Reference](#api-reference)
- [Extraction Filters](#extraction-filters)
- [Supported Telegram URL Formats](#supported-telegram-url-formats)
- [Known Issues & Troubleshooting](#known-issues--troubleshooting)
- [Security Notes](#security-notes)

---

## What This Is

**TeleGrabber** extracts Telegram chat history from university study groups, classifies each message/file using Gemini AI into academic categories, and exports everything to Google Drive in a structured folder layout. The ultimate goal is to provide a clean, structured dataset for **Google NotebookLM** to serve as an AI-powered study assistant.

---

## Architecture Overview

```
NOTEBOOKLM/
├── backend/          # Python FastAPI + Telethon
│   └── app/
│       ├── main.py              # FastAPI entry point
│       ├── config.py            # Pydantic settings (reads .env)
│       ├── db/supabase.py       # Supabase client singleton
│       ├── telegram/
│       │   ├── client.py        # StringSession ↔ Supabase (no .session files)
│       │   ├── parser.py        # Telegram URL parser
│       │   ├── extractor.py     # Concurrent batch-writing loop + asyncio.to_thread
│       │   ├── filters.py       # ExtractionFilters logic
│       │   └── proxy.py         # Auto-proxy discovery (legacy, may be removed)
│       ├── media/
│       │   ├── downloader.py    # Telethon download → Supabase Storage upload (no local storage)
│       │   └── transcriber.py   # Whisper-tiny voice note stub
│       ├── ai/
│       │   ├── categorizer.py   # Gemini / Groq batch tagger
│       │   └── formatter.py     # Markdown/TXT export generator
│       ├── export/
│       │   ├── drive.py         # Google Drive OAuth2 (InstalledAppFlow)
│       │   └── zip_builder.py   # ZIP packager (streams from Supabase Storage)
│       ├── routers/
│       │   ├── auth.py          # /api/auth/*
│       │   ├── extract.py       # /api/extract/*
│       │   └── export.py        # /api/export/*
│       └── models/schemas.py    # Pydantic I/O models
└── frontend/         # Next.js 14 + Shadcn UI
    └── src/
        ├── app/
        │   ├── dashboard/page.tsx   # Main extraction & results UI
        │   └── auth/page.tsx        # Telegram login flow
        └── lib/
            └── api.ts               # Axios wrappers for FastAPI
```

### Key Technical Decisions

| Problem | Solution |
|---|---|
| Local `.session` SQLite files lock under multiple workers | `StringSession` stored in `telegram_sessions` Supabase table |
| FastAPI Event Loop Deadlocks | All Supabase/Storage calls offloaded to thread pools via `asyncio.to_thread` |
| Media filling local disk | Files downloaded to memory → uploaded to Supabase Storage → local file deleted instantly |
| Media Extraction Bottlenecks | `BATCH_SIZE = 50`, semaphore-limited concurrent upload |
| Drive Storage Quota / 403 Errors | Swapped Service Account → OAuth 2.0 `InstalledAppFlow` (user consent) |
| Zombie Jobs after Server Restart | `/stop` endpoint forces Supabase status to `stopped` if background task is dead |

---

## Supabase Schema

### `telegram_sessions`
| Column | Type | Notes |
|---|---|---|
| `phone` | TEXT PK | E.164 format |
| `session_string` | TEXT | Telethon `StringSession` |

### `extraction_jobs`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `phone` | TEXT | FK → telegram_sessions |
| `source_url` | TEXT | Telegram URL |
| `entity_ref` | TEXT | Parsed chat entity |
| `topic_id` | INT | Forum topic (nullable) |
| `link_type` | TEXT | `public_channel`, `private_chat`, `topic_thread`, `invite_link` |
| `status` | TEXT | `pending → running → stopped / completed / failed` |
| `message_count` | INT | Updated live during extraction |
| `filtered_count` | INT | Messages filtered out |
| `filters_json` | JSONB | Stored extraction filters |
| `error_message` | TEXT | Populated on failure |
| `started_at` / `completed_at` / `created_at` | TIMESTAMPTZ | |

### `messages`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | |
| `job_id` | UUID FK | → extraction_jobs |
| `message_id` | BIGINT | Telegram message ID |
| `text` | TEXT | Message content |
| `sender` | TEXT | Username or first name |
| `sender_id` | TEXT | Telegram user ID |
| `date` | TIMESTAMPTZ | Original timestamp |
| `reply_to_msg_id` | BIGINT | Threading info |
| `has_media` | BOOLEAN | True if media was extracted |
| `media_path` | TEXT | Public Supabase Storage URL |
| `is_transcribed` | BOOL | Voice note transcription flag |
| `category` | TEXT | AI-assigned category |

---

## Quick Start

### 1. Clone & Configure

```bash
git clone <your-repo>
cd NOTEBOOKLM
cp .env.example backend/.env
# Edit backend/.env with your credentials
```

### 2. Get Telegram API Credentials

1. Visit [https://my.telegram.org](https://my.telegram.org)
2. Log in → **API Development Tools**
3. Create application → copy `API_ID` and `API_HASH`

### 3. Configure Environment Variables

Edit `backend/.env`:

```env
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_hash_here

SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...   # ← keep secret, server-side only

GEMINI_API_KEY=...

# Google Drive Export (OAuth2 Client ID JSON — NOT a Service Account)
GOOGLE_DRIVE_CREDENTIALS_JSON=c:/Users/MT/Projects/NOTEBOOKLM/backend/google_credentials.json
GOOGLE_DRIVE_FOLDER_ID=...
```

---

## Running the Application

### Terminal 1 — Backend

```powershell
cd backend
.venv\Scripts\activate
# Use uvicorn directly (NOT fastapi dev) to avoid hot-reload killing long extraction jobs
uvicorn app.main:app --port 8000
```

Backend → **http://localhost:8000** | Docs → **http://localhost:8000/docs**

### Terminal 2 — Frontend

```powershell
cd frontend
npm run dev
```

Frontend → **http://localhost:3000**

---

## API Reference

### Auth

```
POST /api/auth/send-code       { "phone": "+12025551234" }
POST /api/auth/verify-code     { "phone": "...", "code": "12345", "phone_code_hash": "..." }
POST /api/auth/verify-2fa      { "phone": "...", "password": "..." }
GET  /api/auth/status?phone=+12025551234
POST /api/auth/clear-session?phone=+12025551234
```

### Extraction

```
POST /api/extract/parse-link   { "url": "https://t.me/c/123/99?topic=456" }
POST /api/extract/start        { "phone": "...", "url": "...", "filters": {...} }
GET  /api/extract/{job_id}/status
POST /api/extract/{job_id}/stop
GET  /api/extract/{job_id}/results?page=1&page_size=100&category=lecture_notes
```

### Export

```
POST /api/export/categorize    { "job_id": "...", "phone": "..." }
POST /api/export/generate      { "job_id": "...", "format": "markdown" }
GET  /api/export/{job_id}/download
POST /api/export/drive-upload  { "job_id": "..." }
```

---

## Extraction Filters

Filters are passed in the `filters` field when starting an extraction:

```json
{
  "start_date": "2024-01-01T00:00:00",
  "end_date": "2024-12-31T23:59:59",
  "senders": ["username1", "username2"],
  "media_type": "all",
  "has_replies": null,
  "search_query": "tutorial"
}
```

| Field | Values | Description |
|---|---|---|
| `start_date` / `end_date` | ISO 8601 | Date range filter |
| `senders` | list of strings | Only include these users |
| `media_type` | `all`, `text_only`, `media_only` | Filter by media presence |
| `has_replies` | `true`, `false`, `null` | Reply filter |
| `search_query` | string | Full-text search in message content |

### AI Category Labels

| Label | Description |
|---|---|
| `lecture_notes` | Typed/scanned lecture slides, notes |
| `past_exam` | Exams, midterms, quizzes |
| `solved_problems` | Worked solutions, examples |
| `homework_assignment` | Raw homework sheets, tasks |
| `textbook_material` | PDF chapters, reference material |
| `summary_cheatsheet` | Formula sheets, quick-reference |
| `subject_media` | Images, diagrams, figures |
| `other` | Off-topic, unclassifiable |

---

## Supported Telegram URL Formats

| Format | Description |
|---|---|
| `t.me/username` | Public channel or group |
| `t.me/c/CHATID/MSGID` | Private group/channel |
| `t.me/c/CHATID/MSGID?topic=ID` | Forum topic thread ✨ |
| `t.me/joinchat/HASH` or `t.me/+HASH` | Invite link |

---

## Known Issues & Troubleshooting

| Issue | Cause | Solution |
|---|---|---|
| "0 messages extracted" | Wrong Telegram URL / channel ID | Verify ID via Telegram Web. Format: `https://t.me/c/EXACT_ID/MSG_ID` |
| "Internal Server Error" on /results | Schema mismatch | Ensure `ExtractedMessageOut.id` is `str` (UUID) in schemas.py |
| Extraction hangs (FloodWaitError) | Telegram rate limiting | Wait and restart the job |
| Dashboard white screen | Backend event loop blocked | Ensure all supabase calls use `asyncio.to_thread()` |
| Drive: "storage quota exceeded" | Service Account has 0 bytes | Use OAuth2 Client ID (Desktop App), NOT a Service Account |
| DNS error after VPN disconnect | VPN locks DNS to static IPs | Reset Wi-Fi DNS to Automatic (DHCP) in network settings |
| Supabase connection fails | Project paused (free tier) | Restore via Supabase dashboard or MCP tool |

---

## Security Notes

- `SUPABASE_SERVICE_ROLE_KEY` **bypasses RLS** — never expose to the browser.
- Session data in `telegram_sessions` = full account login. Treat like a password.
- `google_credentials.json` must be an **OAuth Client ID** (Desktop App), NOT a Service Account.
- Never commit `.env` or `google_credentials.json` to git.
