# TeleGrabber 📡

> Telegram extraction, categorization & management tool — authenticated via MTProto user client, powered by Supabase and Gemini AI, optimized for Google NotebookLM ingest.

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
│       │   └── extractor.py     # Async extraction loop (batch DB writes)
│       ├── media/
│       │   ├── downloader.py    # Chunked media download
│       │   └── transcriber.py   # Whisper-tiny voice note stub
│       ├── routers/
│       │   ├── auth.py          # /api/auth/*
│       │   └── extract.py       # /api/extract/*
│       └── models/schemas.py    # Pydantic I/O models
└── frontend/         # Next.js 14 + Shadcn UI (Phase 2)
```

### Key Design Decisions

| Problem | Solution |
|---|---|
| Local `.session` SQLite files lock under multiple workers | `StringSession` serialized as text, stored in `telegram_sessions` Supabase table |
| Massive in-memory JSON payload from large chats | Batch-writes messages directly to `messages` table during extraction loop |
| Forum topic precision | `iter_messages(reply_to=topic_id)` scopes iterator to exact thread |
| FloodWait errors | `asyncio.sleep(e.seconds + 5)` with job status update |
| Large files (>50 MB) | `iter_download()` chunked streaming |

---

## Supabase Tables (created via MCP)

| Table | Purpose |
|---|---|
| `telegram_sessions` | Stores `StringSession` data per phone, eliminates local session files |
| `extraction_jobs` | Tracks job lifecycle: `pending → running → complete / failed` |
| `messages` | All extracted messages written in batches during extraction |

---

## Quick Start

### 1. Clone & Configure

```bash
git clone <your-repo>
cd NOTEBOOKLM
cp .env.example backend/.env
# Edit backend/.env with your credentials (see below)
```

### 2. Get Telegram API Credentials

1. Visit [https://my.telegram.org](https://my.telegram.org)
2. Log in → **API Development Tools**
3. Create a new application → copy `API_ID` and `API_HASH`

### 3. Configure Environment Variables

Edit `backend/.env`:

```env
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_hash_here

SUPABASE_URL=https://your-project.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_ROLE_KEY=...   # ← keep secret, server-side only

GEMINI_API_KEY=...
```

### 4. Install & Run Backend

```bash
cd backend

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt

uvicorn app.main:app --reload --port 8000
```

Backend runs at **http://localhost:8000**  
Interactive API docs: **http://localhost:8000/docs**

---

## API Reference

### Auth Flow

```
POST /api/auth/send-code       { "phone": "+12025551234" }
POST /api/auth/verify-code     { "phone": "...", "code": "12345", "phone_code_hash": "..." }
POST /api/auth/verify-2fa      { "phone": "...", "password": "..." }   # only if 2FA enabled
GET  /api/auth/status?phone=+12025551234
```

### Extraction Flow

```
POST /api/extract/parse-link   { "url": "https://t.me/c/123/99?topic=456" }
POST /api/extract/start        { "phone": "...", "url": "..." }
GET  /api/extract/{job_id}/status
GET  /api/extract/{job_id}/results?page=1&page_size=100
```

### Supported Telegram URL Formats

| Format | Description |
|---|---|
| `t.me/username` | Public channel or group |
| `t.me/c/CHATID/MSGID` | Private group/channel |
| `t.me/c/CHATID/MSGID?topic=ID` | Forum topic thread ✨ |
| `t.me/joinchat/HASH` or `t.me/+HASH` | Invite link |

---

## Voice Note Transcription (Optional)

Enable by adding to `.env`:
```env
ENABLE_WHISPER=true
WHISPER_MODEL=tiny
```

Install dependencies:
```bash
pip install openai-whisper torch
```

> Voice notes are downloaded as `.ogg`, transcribed with Whisper-tiny, and the transcript is stored as the message `text` with `is_transcribed=true` in the database.

---

## Security Notes

- The `SUPABASE_SERVICE_ROLE_KEY` **bypasses RLS** — only use it server-side. Never expose it to the browser.
- Session data in `telegram_sessions` is equivalent to a full account login. Treat it like a password.
- Add RLS policies to `telegram_sessions` and `messages` when exposing to a multi-tenant frontend.
