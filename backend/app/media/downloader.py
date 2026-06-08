"""
media/downloader.py
────────────────────
Downloads media attached to Telegram messages.

• Files > 50 MB use Telethon's iter_download() for chunked streaming.
• Files are stored under downloads/<chat_id>/<msg_id>_<filename>.
• Returns (relative_path, media_type_string) for DB storage.
"""
from __future__ import annotations

import logging
import mimetypes
from pathlib import Path
from typing import Optional

from telethon.tl.types import (
    Message,
    MessageMediaDocument,
    MessageMediaPhoto,
    DocumentAttributeAudio,
    DocumentAttributeFilename,
    DocumentAttributeVideo,
)

from app.config import settings

logger = logging.getLogger(__name__)

LARGE_FILE_THRESHOLD = 50 * 1024 * 1024  # 50 MB


async def download_media(
    msg: Message,
    entity,
) -> tuple[Optional[str], Optional[str]]:
    """
    Download the media attached to *msg* and return (relative_path, media_type).
    Returns (None, None) if there is no downloadable media.
    """
    if not msg.media:
        return None, None

    chat_id = str(getattr(entity, "id", "unknown"))
    dest_dir = Path(settings.download_dir) / chat_id
    dest_dir.mkdir(parents=True, exist_ok=True)

    # ── Photo ─────────────────────────────────────────────────────────────────
    if isinstance(msg.media, MessageMediaPhoto):
        filename = f"{msg.id}.jpg"
        dest = dest_dir / filename
        await msg.download_media(file=str(dest))
        return await _upload_and_cleanup(dest, chat_id, filename), "photo"

    # ── Document (file, voice, video, audio) ─────────────────────────────────
    if isinstance(msg.media, MessageMediaDocument):
        doc = msg.media.document
        media_type = _detect_media_type(doc)
        filename = _get_filename(doc, msg.id, media_type)
        dest = dest_dir / filename

        if doc.size > LARGE_FILE_THRESHOLD:
            await _chunked_download(msg, dest)
        else:
            await msg.download_media(file=str(dest))

        return await _upload_and_cleanup(dest, chat_id, filename), media_type

    return None, None

async def _upload_and_cleanup(dest: Path, chat_id: str, filename: str) -> str:
    """Upload to Supabase Storage and delete local file to save disk space."""
    from app.db.supabase import get_supabase
    supabase = get_supabase()
    
    storage_path = f"{chat_id}/{filename}"
    
    try:
        import asyncio
        with open(dest, "rb") as f:
            # Read file bytes to avoid passing a closed file handle to the thread
            file_bytes = f.read()
            
        def _sync_upload():
            return supabase.storage.from_("telegrabber-media").upload(
                path=storage_path, 
                file=file_bytes,
                file_options={"upsert": "true"}
            )
            
        # Run the synchronous upload in a thread pool to avoid blocking the event loop
        await asyncio.to_thread(_sync_upload)

        
        # Get public URL
        public_url = supabase.storage.from_("telegrabber-media").get_public_url(storage_path)
    except Exception as e:
        logger.error(f"Failed to upload {filename} to Supabase: {e}")
        # Fallback to local path if upload fails
        return _relative(dest)
        
    # Instantly delete local file to save disk space!
    try:
        if dest.exists():
            dest.unlink()
    except Exception as e:
        logger.error(f"Failed to delete local temp file {dest}: {e}")
        
    return public_url


async def _chunked_download(msg: Message, dest: Path) -> None:
    """Stream-download a large file in 512 KB chunks to avoid OOM."""
    CHUNK = 512 * 1024  # 512 KB
    logger.info("Chunked download → %s", dest)
    with open(dest, "wb") as fh:
        async for chunk in msg.client.iter_download(msg.media, chunk_size=CHUNK):
            fh.write(chunk)


def _detect_media_type(doc) -> str:
    """Classify a Document as voice/video/audio/document based on attributes."""
    for attr in doc.attributes:
        if isinstance(attr, DocumentAttributeAudio):
            return "voice" if attr.voice else "audio"
        if isinstance(attr, DocumentAttributeVideo):
            return "video"
    return "document"


def _get_filename(doc, msg_id: int, media_type: str) -> str:
    """Extract or synthesise a filename for the document."""
    for attr in doc.attributes:
        if isinstance(attr, DocumentAttributeFilename) and attr.file_name:
            return f"{msg_id}_{attr.file_name}"

    ext_map = {
        "voice": ".ogg",
        "audio": ".mp3",
        "video": ".mp4",
        "document": mimetypes.guess_extension(doc.mime_type or "") or ".bin",
    }
    return f"{msg_id}{ext_map.get(media_type, '.bin')}"


def _relative(path: Path) -> str:
    """Return path relative to the downloads root for DB storage."""
    try:
        return str(path.relative_to(Path(settings.download_dir)))
    except ValueError:
        return str(path)
