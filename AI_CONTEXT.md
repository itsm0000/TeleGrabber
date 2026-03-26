# TeleGrabber - AI Context & Product Documentation

## 1. Why we built this
TeleGrabber is an extraction, categorization, and management tool for Telegram chat history. The goal is to ingest massive amounts of unstructured Telegram dialogue, structure it, parse links and media, and ultimately export it into a format perfectly optimized for **Google NotebookLM**. It acts as a bridge between chaotic messaging platforms and AI-driven note-taking/research environments.

## 2. How we want it built (Architecture)
The project is built as a **Full-Stack Application** with a clear separation of concerns:
- **Backend**: FastAPI (Python) using Telethon for genuine MTProto user API authentication. We use a user client rather than a bot to allow extraction from private chats and restricted groups.
- **Database**: Supabase (PostgreSQL) for storing extraction jobs, parsed messages, and Telethon `StringSession` data.
- **Frontend**: Next.js 14 (React) with Shadcn UI (New York style, Zinc palette), styled with Tailwind CSS.
- **Containerization**: `docker-compose.yml` for unified local orchestration.
- **AI Integration**: Google Generative AI (Gemini) for analyzing and categorizing extracted messages before export.

## 3. What features we want to include
The implementation was broken down into 6 Phases:
- **Phase 1: Supabase Schema** (Tables for `telegram_sessions`, `extraction_jobs`, `messages`) [COMPLETED]
- **Phase 2: Project Scaffolding** (Next.js frontend, FastAPI backend skeletons, Docker) [COMPLETED]
- **Phase 3: Backend - Core** (Telethon authentication flow, async extraction loop, DB connection) [COMPLETED]
- **Phase 4: Backend - AI & Export** (Gemini AI categorization, Markdown/TXT generation, Google Drive upload) [PENDING]
- **Phase 5: Frontend - Integration** (Connect Next.js UI to FastAPI endpoints) [PENDING]
- **Phase 6: Polish & Verification** (End-to-end testing, error handling, documentation) [PENDING]

## 4. What issues we are currently having
- **Rate Limiting**: Telegram enforces strict rate limits (`FloodWaitError`). The current extraction loop has basic catching, but needs battle-testing to ensure it doesn't drop jobs on heavy rate-limits.
- **Media Handling**: The `media/downloader.py` currently exists as a skeleton but needs rigorous testing for messages containing albums, large video files (Chunked downloads for >50MB limit), and voice notes.
- **Pydantic Validation**: Relying heavily on `.env` vars means the app crashes immediately on startup if Supabase or Telegram keys are missing. We documented `.env.example`, but runtime warnings might be friendlier for end-users.

## 5. What hasn't been correctly implemented (Immediate Next Steps)
The current AI instance completed Phase 3. The **next instance** must take over starting from **Phase 4**.
Specifically, the following are completely un-implemented:
- **`app/ai/categorizer.py`**: Connect to the Gemini API (`google-generativeai`) to assign topics/categories to batches of stored messages.
- **`app/routers/export.py`**: Endpoints to compile database contents into `.txt` or `.md` files structured specifically for NotebookLM best practices.
- **`app/gdrive/uploader.py`**: Google Drive auto-upload integration.
- **Frontend Wiring**: The Next.js frontend has UI scaffolding but lacks robust state management and actual Axios/Fetch HTTP calls to the operational backend. 

## 6. What features we would like added (Future Enhancements)
- **WebSockets/SSE**: Real-time extraction progress bars in the Next.js UI.
- **Targeted Extraction**: Advanced filtering (by specific dates, specific senders, or media-only) before executing the Telethon extraction loop.
- **Automatic Sync**: Webhook-based or scheduled polling to keep extracting new messages from a chat that was previously processed.

---
**Note to next AI Assistant:** 
Please read `implementation_plan.md` and `task.md` in the artifacts folder for granular checklists before you begin Phase 4!
