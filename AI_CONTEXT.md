# TeleGrabber — AI Context & Product Documentation
> **Last updated:** 2026-03-28 | Phases 1–4 complete. Phase 5 (frontend) is next.
> **For the next AI agent:** Read this file completely before touching any code. This is your single source of truth.

---

## 1. What This Project Is

**TeleGrabber** is a full-stack application that extracts Telegram chat history from university study groups, classifies each message/file using Gemini AI into academic categories, and exports everything to Google Drive in a structured folder layout — so the user can drag that folder into **Google NotebookLM** as a source and use it as an AI-powered study assistant.

**The real-world use case:** University students share lecture notes, past exams, solved problems, PDFs, and images in Telegram groups. This tool grabs all of that, organizes it by type, and makes it queryable via NotebookLM.

---

## 2. Architecture

| Layer | Technology | Notes |
|---|---|---|
| **Backend API** | FastAPI (Python 3.13) + Uvicorn | Async, runs on port 8000 |
| **Telegram client** | Telethon (MTProto user client) | Logs in as a real user, NOT a bot |
| **Session storage** | Supabase `telegram_sessions` table | `StringSession` strings — no `.session` files |
| **Data storage** | Supabase PostgreSQL (`AKONY` project) | Project ID: `dkkzpaxuvemxumhmrdzp` |
| **AI classification** | Google Gemini 2.0 Flash | Batched, 50 messages per API call |
| **Export** | Local filesystem + Google Drive | Service-account upload, per-category subfolders |
| **Frontend** | Next.js 14 (App Router) + Tailwind CSS + Shadcn UI | New York style, Zinc palette — currently unconnected scaffolding |
| **Containerization** | `docker-compose.yml` exists | Not yet fully configured for Phase 4+ |

---

## 3. Repository Structure

```
NOTEBOOKLM/
├── backend/
│   ├── app/
│   │   ├── main.py                  # FastAPI app, CORS, lifespan hooks
│   │   ├── config.py                # Pydantic Settings — loads all env vars
│   │   ├── db/
│   │   │   └── supabase.py          # Singleton Supabase client (service-role key)
│   │   ├── telegram/
│   │   │   ├── client.py            # StringSession ↔ Supabase, get_client(), save_session()
│   │   │   ├── parser.py            # Telegram URL → ParsedLink (public/private/topic)
│   │   │   └── extractor.py         # Async batch-writing extraction loop + FloodWait handling
│   │   ├── media/
│   │   │   ├── downloader.py        # Chunked download for files >50MB
│   │   │   └── transcriber.py       # Whisper-tiny stub (not yet active)
│   │   ├── ai/
│   │   │   ├── categorizer.py       # Gemini 2.0 Flash batch tagger
│   │   │   └── formatter.py         # Markdown/TXT export generator for NotebookLM
│   │   ├── export/
│   │   │   ├── zip_builder.py       # ZIP packager (export doc + media)
│   │   │   └── drive.py             # Google Drive service-account uploader
│   │   ├── routers/
│   │   │   ├── auth.py              # /api/auth/* — send-code, verify-code, verify-2fa, status
│   │   │   ├── extract.py           # /api/extract/* — parse-link, start, status, results
│   │   │   └── export.py            # /api/export/* — categorize, generate, download, drive-upload
│   │   └── models/
│   │       └── schemas.py           # All Pydantic request/response models
│   ├── exports/                     # Generated export files (gitignored)
│   ├── downloads/                   # Downloaded media (gitignored)
│   ├── requirements.txt
│   └── .env                         # Real credentials — NEVER commit this
├── frontend/
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx           # Root layout
│   │   │   └── page.tsx             # Default Next.js placeholder (NOT yet replaced)
│   │   ├── components/              # Empty — no custom components built yet
│   │   └── lib/                     # Empty — no utilities built yet
│   └── package.json
├── .env.example                     # Documents all required env vars (fully written)
├── docker-compose.yml               # Exists but needs update for Phase 4+ vars
├── AI_CONTEXT.md                    # This file
└── README.md                        # Setup instructions
```

---

## 4. Supabase Database Schema

**Project:** `AKONY` | **Project ID:** `dkkzpaxuvemxumhmrdzp` | **Region:** `ap-northeast-2`

### Table: `telegram_sessions`
| Column | Type | Notes |
|---|---|---|
| `phone` | TEXT PK | E.164 format |
| `session_string` | TEXT | Telethon `StringSession` — treat like a password |
| `created_at` | TIMESTAMPTZ | |

### Table: `extraction_jobs`
| Column | Type | Notes |
|---|---|---|
| `id` | UUID PK | Auto-generated |
| `phone` | TEXT | Which user session ran this |
| `source_url` | TEXT | The Telegram URL that was extracted |
| `entity_ref` | TEXT | Parsed chat entity (username or numeric ID) |
| `topic_id` | INT | Forum topic thread ID (nullable) |
| `link_type` | TEXT | `public_channel`, `private_chat`, `topic_thread`, `invite_link` |
| `status` | TEXT | `pending → running → complete / failed` |
| `message_count` | INT | Updated during extraction |
| `error_message` | TEXT | Populated on failure |
| `started_at` | TIMESTAMPTZ | |
| `completed_at` | TIMESTAMPTZ | |
| `created_at` | TIMESTAMPTZ | |

### Table: `messages`
| Column | Type | Notes |
|---|---|---|
| `id` | BIGINT PK | Auto-increment |
| `job_id` | UUID FK | → `extraction_jobs.id` |
| `message_id` | BIGINT | Telegram message ID |
| `text` | TEXT | Message text content |
| `sender` | TEXT | Username or first name |
| `sender_id` | TEXT | Telegram user ID |
| `date` | TIMESTAMPTZ | Original message timestamp |
| `reply_to_msg_id` | BIGINT | Threading info |
| `media_path` | TEXT | Local path to downloaded media file (nullable) |
| `is_transcribed` | BOOL | Voice note transcription flag |
| `category` | TEXT | **Added Phase 4** — one of 8 academic labels (nullable until categorized) |

**Key constraint:** `UNIQUE (job_id, message_id)` — all batch upserts are idempotent.
**Indexes:** `messages(job_id)`, `messages(date)`, `messages(reply_to_msg_id)`, `messages(category)`, `extraction_jobs(status)`

---

## 5. All API Endpoints

Base URL: `http://localhost:8000` | Interactive docs: `http://localhost:8000/docs`

### Auth (`/api/auth`)
| Method | Path | Description |
|---|---|---|
| POST | `/api/auth/send-code` | Send OTP to phone via Telegram |
| POST | `/api/auth/verify-code` | Submit OTP; returns `2FA_REQUIRED` if applicable |
| POST | `/api/auth/verify-2fa` | Submit cloud password |
| GET | `/api/auth/status?phone=+XX` | Check if session is still live |

### Extraction (`/api/extract`)
| Method | Path | Description |
|---|---|---|
| POST | `/api/extract/parse-link` | Parse Telegram URL → entity, topic_id, link_type |
| POST | `/api/extract/start` | Create job + start async extraction background task |
| GET | `/api/extract/{job_id}/status` | Poll job progress |
| GET | `/api/extract/{job_id}/results` | Paginated extracted messages (default 100, max 500) |

### Export (`/api/export`)
| Method | Path | Description |
|---|---|---|
| POST | `/api/export/categorize` | Run Gemini 2.0 Flash tagger on all uncategorized messages for a job |
| POST | `/api/export/generate` | Generate `.md` or `.txt` export file from categorized messages |
| GET | `/api/export/{job_id}/download` | Stream ZIP archive (export doc + media) |
| POST | `/api/export/drive-upload` | Upload export to Google Drive with per-category subfolders |

### Meta
| Method | Path | Description |
|---|---|---|
| GET | `/health` | `{"status": "ok", "version": "0.1.0"}` |

---

## 6. AI Category Taxonomy

The Gemini categorizer tags each message with exactly one of these labels:

| Label | What Gets Tagged |
|---|---|
| `lecture_notes` | Typed/scanned lecture slides, handwritten notes, typed summaries |
| `past_exam` | Final exams, midterms, quizzes — solved OR unsolved |
| `solved_problems` | Worked solutions, solved exercises, example answer sheets |
| `homework_assignment` | Raw homework sheets, lab tasks, assignments not yet solved |
| `textbook_material` | PDF chapters, official reference material excerpts |
| `summary_cheatsheet` | Formula sheets, revision notes, cheat sheets, quick-reference cards |
| `subject_media` | Images, diagrams, figures, infographics related to the subject |
| `other` | Off-topic chat, links without content, unclassifiable text |

---

## 7. Environment Variables

Full `.env.example` is at the repo root. Required variables for `backend/.env`:

```bash
# Telegram (from my.telegram.org)
TELEGRAM_API_ID=30619302
TELEGRAM_API_HASH=a501dc4dd3e7e2288cdc3dc18ff9e3ce

# Supabase (project: AKONY, ID: dkkzpaxuvemxumhmrdzp)
SUPABASE_URL=https://dkkzpaxuvemxumhmrdzp.supabase.co
SUPABASE_ANON_KEY=eyJhbGci...   # see dashboard
SUPABASE_SERVICE_ROLE_KEY=eyJhbGci...  # see dashboard → Settings → API

# Gemini AI
GEMINI_API_KEY=AIzaSyCWa68G_ErEdfwy7uQrhZoq4HhaC51ATIs

# Google Drive (optional — all export works without these)
GOOGLE_DRIVE_CREDENTIALS_JSON=   # abs path to service-account .json
GOOGLE_DRIVE_FOLDER_ID=          # target Drive folder ID

# Local dirs (defaults shown)
EXPORT_DIR=exports
DOWNLOAD_DIR=downloads
CORS_ORIGINS=["http://localhost:3000"]
ENABLE_WHISPER=false
```

> ⚠️ The `.env` file is populated with real credentials on disk but is gitignored. Never commit it.

---

## 8. Phase Completion Status

| Phase | Description | Status |
|---|---|---|
| **Phase 1** | Supabase schema (`telegram_sessions`, `extraction_jobs`, `messages`) | ✅ Complete |
| **Phase 2** | Project scaffolding (FastAPI backend, Next.js frontend, Docker) | ✅ Complete |
| **Phase 3** | Backend core (Telethon auth flow, async extraction loop, DB writes) | ✅ Complete |
| **Phase 4** | AI categorization (Gemini), Markdown/TXT export, ZIP builder, Google Drive uploader, export router | ✅ Complete |
| **Phase 5** | Frontend wiring — connect Next.js UI to all FastAPI endpoints | 🔴 Not started |
| **Phase 6** | Polish — end-to-end testing, README update, docker-compose, error handling | 🔴 Not started |

---

## 9. Current Known Issues & Bugs

### Critical
- **`FloodWaitError` drops jobs permanently** — The current extractor marks the job `failed` on a `FloodWaitError` instead of pausing and resuming. Should be changed to: update status to `paused`, sleep for `e.seconds + 5`, then continue `iter_messages()` from the last processed offset.
- **`_pending_hashes` is in-memory only** — The `phone_code_hash` from Telegram OTP is stored in a Python dict in `auth.py`. If the server restarts between `send-code` and `verify-code`, the hash is lost and the user must restart the auth flow. Should be stored in Supabase or Redis.

### Medium
- **`categorize_job()` is not truly async** — `google.generativeai` uses blocking sync calls. Under load this will block the FastAPI event loop. Must be wrapped with `asyncio.to_thread()` or migrated to the `google-genai` async client.
- **No job uniqueness guard** — Nothing prevents a user from starting two extraction jobs for the same URL simultaneously, leading to duplicate rows in `messages` (the unique constraint on `(job_id, message_id)` only protects within one job; two jobs for the same URL will create two separate sets of duplicates).
- **Media files are not downloaded during extraction** — `extractor.py` has `media_path` commented out. The `downloader.py` module exists but is never called. The `category` column for media-only messages will always fall back to `subject_media` or `other` since there's no text to classify.
- **`formatter.py` has a bug in `_render_txt()`** — The emoji-stripping logic `replace(next(iter(cat_display)), "", 1)` only removes the first character, not the full emoji. Some emojis are multi-codepoint and this will corrupt the string.

### Minor
- **`docker-compose.yml` is outdated** — Does not include the Phase 4 environment variables (`GEMINI_API_KEY`, `GOOGLE_DRIVE_*`, `EXPORT_DIR`, `DOWNLOAD_DIR`).
- **No request timeout on Gemini calls** — If the Gemini API hangs, the categorize endpoint will block indefinitely.
- **`exports/` and `downloads/` directories must be manually created** — The code creates them via `mkdir(parents=True, exist_ok=True)` but this hasn't been smoke-tested end-to-end.
- **`CORS_ORIGINS` parsing** — The value is stored as a JSON string `["http://localhost:3000"]` in `.env` but `pydantic-settings` may or may not parse it correctly depending on version. Worth testing explicitly.

---

## 10. What Has Not Been Implemented Yet

### Phase 5 — Frontend (Highest Priority)
The frontend is a **bare Next.js 14 scaffolding** (`page.tsx` still shows the default Next.js boilerplate). Nothing has been built. Required pages and components:

- **`/auth` page** — Phone number input → OTP input → optional 2FA password. Calls `/api/auth/send-code`, `/api/auth/verify-code`, `/api/auth/verify-2fa`. On success, stores phone in `localStorage` or context.
- **`/dashboard` page** — Main control panel:
  - Text input for Telegram URL
  - "Start Extraction" button → calls `/api/extract/start`
  - Live job status polling (`/api/extract/{job_id}/status`) with a progress bar
  - "Categorize" button → calls `/api/export/categorize`
  - "Export Markdown" / "Export TXT" buttons → calls `/api/export/generate`
  - "Download ZIP" button → hits `/api/export/{job_id}/download`
  - "Push to Drive" button → calls `/api/export/drive-upload`
- **Messages table** — Paginated view of extracted messages with:
  - Filter by `category` label (tabs or dropdown)
  - Filter by `sender`
  - Filter by date range
  - Display `media_path` as a badge if present
- **Job history** — List of all past extraction jobs with status indicators

### Phase 6 — Polish
- End-to-end smoke test (boot server → auth → extract → categorize → export → download)
- Update `README.md` with Phase 4+ setup instructions (Google Drive service account setup is not yet documented)
- Update `docker-compose.yml` with all env vars
- Add graceful startup validation: warn (not crash) if optional vars like `GEMINI_API_KEY` or `GOOGLE_DRIVE_CREDENTIALS_JSON` are missing

---

## 11. Features Not Yet Thought About (Worth Considering)

### High Value
- **Media type detection before download** — Before downloading, inspect the Telegram `MessageMedia` type (photo, document, video, voice). Skip types the user doesn't want (e.g. stickers, GIFs) and only download PDFs, images, and voice notes. This prevents filling disk with junk.
- **Subject/course tagging** — Beyond category labels, add a second AI pass that extracts the academic **subject name** (e.g. "Digital Logic", "Calculus II", "OS") from the message content. Store as a `subject` column. This makes the Drive export structure `/{subject}/{category}/` which is far more useful in NotebookLM.
- **Duplicate file detection** — Multiple people share the same PDF in a group. Before downloading, hash the file and skip if already saved. Store file hashes in a `media_hashes` table.
- **Extraction resume / incremental sync** — After initial extraction, allow re-running on the same URL to only fetch messages newer than the last `max(date)` in the `messages` table for that job. This keeps an up-to-date snapshot over time.
- **SSE (Server-Sent Events) for real-time progress** — Currently extraction progress is polled. Replace with a proper SSE stream from `/api/extract/{job_id}/stream` so the frontend can show a live bar without hammering the API.

### Medium Value
- **Forward to Saved Messages** — After categorization, let the user select specific categories and forward those messages to their Telegram Saved Messages, creating a personal curated feed.
- **Multi-job batch** — Submit multiple Telegram URLs at once (e.g. several course groups), run extraction in parallel (with rate-limit awareness), and merge the results into one categorized export.
- **Custom category rename** — Let the user override the AI's category for individual messages via the frontend UI, with the correction upserted back to Supabase.
- **Export directly to NotebookLM** — NotebookLM has no public API yet, but the Drive folder approach already achieves this. Watch for a NotebookLM API when Google releases it.
- **Webhook/scheduled sync** — Telegram bots can receive new messages via webhook. As a complement to the user client, set up a bot in the same group to receive and classify new messages automatically on a schedule.

### Lower Priority
- **Voice note transcription (Whisper)** — `transcriber.py` is already a stub. Wire it to the actual Whisper-tiny model. Transcriptions would make voice notes searchable in NotebookLM.
- **OCR for scanned PDFs / images** — Many university PDFs are scans. Pass image attachments through a Vision API (Gemini Vision is already available) to extract text, then store as `text` in the messages table for better classification.
- **Multi-user / auth token system** — Currently the app is designed for a single personal user. Adding JWT auth to the FastAPI layer would allow sharing the tool with classmates.
- **Compressed media re-upload** — Before uploading to Drive, compress large images/PDFs to save quota.

---

## 12. How to Run Locally

```bash
# Backend
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# API docs: http://localhost:8000/docs

# Frontend
cd frontend
npm install
npm run dev
# App: http://localhost:3000
```

---

## 13. Google Drive Setup (for Phase 4 Drive upload)

1. Go to [Google Cloud Console](https://console.cloud.google.com) → create a project → enable **Google Drive API**
2. Create a **Service Account** → download the JSON key
3. In Google Drive, create a folder → share it with the service account email (Editor access)
4. Copy the folder ID from the Drive URL: `drive.google.com/drive/folders/{FOLDER_ID}`
5. Set in `backend/.env`:
   ```
   GOOGLE_DRIVE_CREDENTIALS_JSON=/absolute/path/to/service-account.json
   GOOGLE_DRIVE_FOLDER_ID=your_folder_id_here
   ```

The uploader will create: `{your folder}/TeleGrabber — {job_id}/lecture_notes/`, `past_exam/`, etc. Add the top-level folder to NotebookLM as a Google Drive source.

---

## 14. Git History Context

| Commit | What it covered |
|---|---|
| Initial commits | Supabase schema, backend scaffolding, frontend scaffolding |
| `c39f957` | Phase 3 complete — Telethon auth, extraction loop, all core backend modules |
| `3d713bc` | **Phase 4 complete** — AI categorizer, formatter, Drive uploader, export router, schemas, config, env |

**Branch:** `main` — all commits push directly to main. No feature branches yet.

---

**Note to next AI instance:** Start by reading this file, then look at `backend/app/routers/export.py` and `backend/app/ai/categorizer.py` to understand the Phase 4 contracts before building Phase 5. The frontend lives in `frontend/src/` and currently contains only Next.js boilerplate — replace `page.tsx` and build the auth + dashboard pages. Use the Shadcn UI components that are already initialized (New York style, Zinc palette). All API calls from the frontend should target `http://localhost:8000`.
