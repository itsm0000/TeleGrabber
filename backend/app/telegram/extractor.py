import asyncio
import logging
from uuid import UUID
from datetime import datetime
from telethon import TelegramClient
from telethon.errors import FloodWaitError

from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)
BATCH_SIZE = 100

async def run_extraction(
    job_id: UUID,
    client: TelegramClient,
    entity_ref: str,
    topic_id: int | None
):
    """Background task to extract messages asynchronously from a Telegram chat/topic."""
    supabase = get_supabase()
    
    try:
        supabase.table("extraction_jobs").update({
            "status": "running",
            "started_at": datetime.utcnow().isoformat()
        }).eq("id", str(job_id)).execute()

        entity = await client.get_entity(entity_ref)
        kwargs = {}
        if topic_id:
            kwargs["reply_to"] = topic_id
            
        messages_batch = []
        total_extracted = 0

        async for message in client.iter_messages(entity, **kwargs):
            if not message.text and not message.media:
                continue

            # Basic extraction - media files will be handled separately if needed
            msg_data = {
                "job_id": str(job_id),
                "message_id": message.id,
                "text": message.text or "",
                "sender": getattr(message.sender, 'username', None) or getattr(message.sender, 'first_name', "Unknown") if message.sender else "Unknown",
                "sender_id": str(message.sender_id) if getattr(message, 'sender_id', None) else None,
                "date": message.date.isoformat(),
                "reply_to_msg_id": message.reply_to.reply_to_msg_id if getattr(message, 'reply_to', None) else None,
                # "media_path": None, # to be updated by media handler in future
                # "is_transcribed": False
            }
            messages_batch.append(msg_data)
            
            if len(messages_batch) >= BATCH_SIZE:
                supabase.table("messages").upsert(messages_batch).execute()
                total_extracted += len(messages_batch)
                
                supabase.table("extraction_jobs").update({
                    "message_count": total_extracted
                }).eq("id", str(job_id)).execute()
                
                messages_batch = []

        if messages_batch:
            supabase.table("messages").upsert(messages_batch).execute()
            total_extracted += len(messages_batch)

        supabase.table("extraction_jobs").update({
            "status": "complete",
            "message_count": total_extracted,
            "completed_at": datetime.utcnow().isoformat()
        }).eq("id", str(job_id)).execute()
        
        logger.info(f"Extraction job {job_id} complete. {total_extracted} messages.")

    except FloodWaitError as e:
        logger.warning(f"FloodWaitError: sleeping for {e.seconds + 5} seconds.")
        supabase.table("extraction_jobs").update({
            "status": "failed",
            "error_message": f"FloodWaitError: {e.seconds}s"
        }).eq("id", str(job_id)).execute()

    except Exception as e:
        logger.exception(f"Extraction failed for job {job_id}")
        supabase.table("extraction_jobs").update({
            "status": "failed",
            "error_message": str(e)
        }).eq("id", str(job_id)).execute()
