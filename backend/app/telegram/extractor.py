import asyncio
import logging
from uuid import UUID
from datetime import datetime, date
from telethon import TelegramClient
from telethon.errors import FloodWaitError, NotFoundError
import re
from typing import cast, Any, Optional

from app.models.schemas import ExtractionFilters
from app.db.supabase import get_supabase
from app.media.downloader import download_media

logger = logging.getLogger(__name__)


def get_file_extension(filename: str) -> str:
    """Extract file extension from filename, lowercase."""
    if not filename:
        return ""
    parts = filename.rsplit(".", 1)
    if len(parts) > 1:
        return "." + parts[1].lower()
    return ""


def message_matches_filters(message, filters: Optional[ExtractionFilters]) -> bool:
    """Check if a message matches the given filters. Returns True if message should be included."""
    if filters is None:
        return True

    # ── Time Scope ──────────────────────────────────────────────────────
    if filters.date_from:
        msg_date = (
            message.date.date() if hasattr(message.date, "date") else message.date
        )
        if msg_date < filters.date_from:
            return False

    if filters.date_to:
        msg_date = (
            message.date.date() if hasattr(message.date, "date") else message.date
        )
        if msg_date > filters.date_to:
            return False

    # ── Content Type Filter ─────────────────────────────────────────────
    if filters.media_types:
        has_text = bool(message.text)
        has_photo = bool(message.photo)
        has_video = bool(message.video) and not bool(message.gif)  # video but not gif
        has_document = bool(message.document)
        has_audio = bool(message.audio) or bool(message.voice)
        has_sticker = bool(message.sticker)
        has_gif = bool(message.gif)
        has_poll = bool(message.poll)

        type_matched = False
        for media_type in filters.media_types:
            if (
                media_type == "text"
                and has_text
                and not any(
                    [
                        has_photo,
                        has_video,
                        has_document,
                        has_audio,
                        has_sticker,
                        has_gif,
                        has_poll,
                    ]
                )
            ):
                type_matched = True
            elif media_type == "image" and has_photo:
                type_matched = True
            elif media_type == "video" and has_video:
                type_matched = True
            elif media_type == "document" and has_document:
                type_matched = True
            elif media_type == "audio" and has_audio:
                type_matched = True
            elif media_type == "sticker" and has_sticker:
                type_matched = True
            elif media_type == "gif" and has_gif:
                type_matched = True
            elif media_type == "poll" and has_poll:
                type_matched = True

        if not type_matched:
            return False

    # ── File Extension Filter ───────────────────────────────────────────
    if filters.file_extensions and message.document:
        doc_name = getattr(message.document, "attributes", [{}])
        filename = ""
        for attr in doc_name:
            if hasattr(attr, "file_name"):
                filename = attr.file_name or ""
                break

        ext = get_file_extension(filename)
        if ext:
            allowed_exts = [
                e.lower() if e.startswith(".") else "." + e.lower()
                for e in filters.file_extensions
            ]
            if ext not in allowed_exts:
                return False

    # ── Sender Filter ───────────────────────────────────────────────────
    sender_username = None
    sender_id = None
    if message.sender:
        sender_username = getattr(message.sender, "username", None)
        sender_id = (
            str(message.sender_id) if getattr(message, "sender_id", None) else None
        )

    if filters.senders:
        sender_match = False
        for s in filters.senders:
            s_lower = s.lower().lstrip("@")
            if sender_username and sender_username.lower() == s_lower:
                sender_match = True
            elif sender_id and sender_id == s_lower:
                sender_match = True
        if not sender_match:
            return False

    if filters.exclude_senders:
        for s in filters.exclude_senders:
            s_lower = s.lower().lstrip("@")
            if sender_username and sender_username.lower() == s_lower:
                return False
            elif sender_id and sender_id == s_lower:
                return False

    # ── Keyword Filter ──────────────────────────────────────────────────
    if filters.keywords and message.text:
        text_lower = message.text.lower()
        keywords_lower = [k.lower() for k in filters.keywords]

        if filters.keywords_match == "all":
            if not all(k in text_lower for k in keywords_lower):
                return False
        else:  # "any"
            if not any(k in text_lower for k in keywords_lower):
                return False
    elif filters.keywords and not message.text:
        return False

    # ── Hashtag Filter ──────────────────────────────────────────────────
    if filters.hashtags and message.text:
        text_lower = message.text.lower()
        found_hashtag = False
        for tag in filters.hashtags:
            tag_clean = tag.lower() if tag.startswith("#") else "#" + tag.lower()
            if tag_clean in text_lower:
                found_hashtag = True
                break
        if not found_hashtag:
            return False

    # ── Link Filter ─────────────────────────────────────────────────────
    if filters.has_links is True:
        if not message.text or not re.search(r"https?://\S+", message.text):
            return False

    # ── View Count Filter ───────────────────────────────────────────────
    if filters.min_views is not None:
        views = getattr(message, "views", None) or 0
        if views < filters.min_views:
            return False

    # ── Media Properties ────────────────────────────────────────────────
    if filters.min_file_size is not None or filters.max_file_size is not None:
        if message.document:
            file_size = getattr(message.document, "size", None)
            if file_size is not None:
                if (
                    filters.min_file_size is not None
                    and file_size < filters.min_file_size
                ):
                    return False
                if (
                    filters.max_file_size is not None
                    and file_size > filters.max_file_size
                ):
                    return False

    if filters.min_video_duration is not None or filters.max_video_duration is not None:
        if message.video:
            duration = getattr(message.video, "duration", None)
            if duration is not None:
                if (
                    filters.min_video_duration is not None
                    and duration < filters.min_video_duration
                ):
                    return False
                if (
                    filters.max_video_duration is not None
                    and duration > filters.max_video_duration
                ):
                    return False

    return True


BATCH_SIZE = 50
# In-memory cancellation events: job_id -> asyncio.Event
_cancellation_events: dict[str, asyncio.Event] = {}


def get_cancellation_event(job_id: UUID) -> asyncio.Event:
    """Get or create a cancellation event for a job."""
    key = str(job_id)
    if key not in _cancellation_events:
        _cancellation_events[key] = asyncio.Event()
    return _cancellation_events[key]


def cancel_job(job_id: UUID) -> bool:
    """Signal a job to stop. Returns True if job was found and cancelled."""
    key = str(job_id)
    if key in _cancellation_events:
        _cancellation_events[key].set()
        return True
    return False


def cleanup_cancellation_event(job_id: UUID):
    """Remove the cancellation event after job completion."""
    key = str(job_id)
    _cancellation_events.pop(key, None)


async def run_extraction(
    job_id: UUID,
    client: TelegramClient,
    entity_ref: str,
    topic_id: int | None,
    max_messages: int | None = None,
    filters: Optional[ExtractionFilters] = None,
):
    """Background task to extract messages asynchronously from a Telegram chat/topic.

    Supports comprehensive filtering via ExtractionFilters.
    """
    supabase = get_supabase()
    cancel_event = get_cancellation_event(job_id)

    logger.info(f"Starting extraction job {job_id} for entity {entity_ref}")
    logger.info(
        f"Client connected: {client.is_connected()}, authorized: {await client.is_user_authorized()}"
    )
    if max_messages:
        logger.info(f"Max messages limit: {max_messages}")
    if filters:
        logger.info(f"Filters applied: {filters.dict(exclude_none=True)}")

    try:
        await asyncio.to_thread(
            lambda: supabase.table("extraction_jobs").update(
                {"status": "running", "started_at": datetime.utcnow().isoformat()}
            ).eq("id", str(job_id)).execute()
        )

        logger.info(
            f"Attempting to resolve entity: {entity_ref} (type: {type(entity_ref)})"
        )
        try:
            # If entity_ref is a numeric string, convert it to int for get_entity
            parsed_entity_ref = int(entity_ref) if entity_ref.lstrip('-').isdigit() else entity_ref
            entity = await client.get_entity(parsed_entity_ref)
            if isinstance(entity, list):
                logger.warning(
                    f"get_entity returned a list of {len(entity)} entities; using first"
                )
                entity = entity[0]
            assert not isinstance(entity, list)
            entity = cast(Any, entity)
            logger.info(
                f"Entity resolved: {entity.id} - {getattr(entity, 'title', 'No title')}"
            )
        except Exception as entity_err:
            logger.error(
                f"Failed to resolve entity {entity_ref}: {type(entity_err).__name__}: {entity_err}"
            )
            # Try alternative formats for private channels
            if entity_ref.startswith("-100"):
                alt_ref = entity_ref[4:]  # Try without -100 prefix
                logger.info(f"Trying alternative format: {alt_ref}")
                try:
                    entity = await client.get_entity(int(alt_ref))
                    if isinstance(entity, list):
                        logger.warning(
                            f"get_entity returned a list of {len(entity)} entities; using first"
                        )
                        entity = entity[0]
                    assert not isinstance(entity, list)
                    entity = cast(Any, entity)
                    logger.info(f"Entity resolved with alt format: {entity.id}")
                except Exception as alt_err:
                    logger.error(f"Alternative format also failed: {alt_err}")
                    # Last resort: fetch dialogs to populate cache, then retry
                    logger.info(
                        "Attempting to fetch dialogs to populate entity cache..."
                    )
                    try:
                        # Fetch up to 200 dialogs (should include private channels)
                        await client.get_dialogs(limit=200)
                        # Retry original entity_ref
                        entity = await client.get_entity(parsed_entity_ref)
                        if isinstance(entity, list):
                            entity = entity[0]
                        entity = cast(Any, entity)
                        logger.info(
                            f"Entity resolved after dialog refresh: {entity.id}"
                        )
                    except Exception as final_err:
                        logger.error(f"All resolution attempts failed: {final_err}")
                        raise entity_err  # Raise original error
            else:
                # For non -100 prefixed refs, also try dialog refresh
                logger.info("Attempting to fetch dialogs to populate entity cache...")
                try:
                    await client.get_dialogs(limit=200)
                    entity = await client.get_entity(parsed_entity_ref)
                    if isinstance(entity, list):
                        entity = entity[0]
                    entity = cast(Any, entity)
                    logger.info(f"Entity resolved after dialog refresh: {entity.id}")
                except Exception as final_err:
                    logger.error(f"Dialog refresh resolution failed: {final_err}")
                    raise entity_err  # Raise original error
        # Ensure entity is a single entity, not a list
        if isinstance(entity, list):
            logger.warning(
                f"get_entity returned a list of {len(entity)} entities; using first"
            )
            entity = entity[0]

        kwargs = {}
        if topic_id:
            kwargs["reply_to"] = topic_id

        messages_batch = []
        pending_media_tasks = []
        total_extracted = 0
        total_media_count = 0
        total_media_size = 0
        stopped_early = False

        media_semaphore = asyncio.Semaphore(50)

        async def _download_and_update(msg, msg_dict, ent):
            async with media_semaphore:
                try:
                    m_path, m_type = await download_media(msg, ent)
                    msg_dict["media_path"] = m_path
                    msg_dict["media_type"] = m_type
                    msg_dict["has_media"] = bool(m_path)
                except Exception as e:
                    logger.error(f"Failed to download media for message {msg.id}: {e}")


        async for message in client.iter_messages(entity, **kwargs):
            # Check for cancellation
            if cancel_event.is_set():
                logger.info(
                    f"Job {job_id} was cancelled after {total_extracted} messages"
                )
                stopped_early = True
                break

            # Check max_messages limit
            if max_messages and total_extracted >= max_messages:
                logger.info(f"Job {job_id} reached max_messages limit ({max_messages})")
                break

            # Check filters
            if not message_matches_filters(message, filters):
                continue

            # Check media limits (if filters include max_media_count or max_total_size)
            has_media = bool(
                message.photo
                or message.video
                or message.document
                or message.audio
                or message.voice
                or message.sticker
                or message.gif
            )
            if has_media:
                # Determine media size (only document size)
                media_size = 0
                if message.document:
                    media_size = getattr(message.document, "size", 0) or 0

                if (
                    filters
                    and filters.max_media_count is not None
                    and total_media_count >= filters.max_media_count
                ):
                    logger.debug(
                        f"Skipping message {message.id}: max_media_count reached"
                    )
                    continue
                if (
                    filters
                    and filters.max_total_size is not None
                    and total_media_size + media_size > filters.max_total_size
                ):
                    logger.debug(
                        f"Skipping message {message.id}: max_total_size would be exceeded"
                    )
                    continue
                total_media_count += 1
                total_media_size += media_size

            if not message.text and not message.media:
                continue

            # Basic extraction (media updated concurrently if present)
            msg_data = {
                "job_id": str(job_id),
                "message_id": message.id,
                "text": message.text or "",
                "sender": getattr(message.sender, "username", None)
                or getattr(message.sender, "first_name", "Unknown")
                if message.sender
                else "Unknown",
                "sender_id": str(message.sender_id)
                if getattr(message, "sender_id", None)
                else None,
                "date": message.date.isoformat(),
                "reply_to_msg_id": message.reply_to.reply_to_msg_id
                if getattr(message, "reply_to", None)
                else None,
                "media_path": None,
                "media_type": None,
                "has_media": False,
            }

            if message.media:
                task = asyncio.create_task(_download_and_update(message, msg_data, entity))
                pending_media_tasks.append(task)
            messages_batch.append(msg_data)

            if len(messages_batch) >= BATCH_SIZE:
                if pending_media_tasks:
                    await asyncio.gather(*pending_media_tasks, return_exceptions=True)
                    pending_media_tasks = []

                await asyncio.to_thread(
                    lambda: supabase.table("messages").upsert(messages_batch).execute()
                )
                total_extracted += len(messages_batch)

                # ── Check if externally stopped (DB is the source of truth) ────────
                # This handles cases where the backend reloaded and the in-memory
                # cancel_event was wiped, but the DB was set to 'stopped'.
                _status_check = await asyncio.to_thread(
                    lambda: supabase.table("extraction_jobs")
                        .select("status")
                        .eq("id", str(job_id))
                        .maybe_single()
                        .execute()
                )
                _db_status = (_status_check.data or {}).get("status")
                if _db_status == "stopped" or cancel_event.is_set():
                    logger.info(
                        f"Job {job_id} halted after {total_extracted} messages "
                        f"(db_status={_db_status}, cancel_event={cancel_event.is_set()})"
                    )
                    stopped_early = True
                    messages_batch = []
                    break

                await asyncio.to_thread(
                    lambda: supabase.table("extraction_jobs").update(
                        {"message_count": total_extracted}
                    ).eq("id", str(job_id)).execute()
                )

                messages_batch = []

        if messages_batch and not stopped_early:
            if pending_media_tasks:
                await asyncio.gather(*pending_media_tasks, return_exceptions=True)
                pending_media_tasks = []

            await asyncio.to_thread(
                lambda: supabase.table("messages").upsert(messages_batch).execute()
            )
            total_extracted += len(messages_batch)

        # Determine final status
        final_status = "stopped" if stopped_early else "complete"

        await asyncio.to_thread(
            lambda: supabase.table("extraction_jobs").update(
                {
                    "status": final_status,
                    "message_count": total_extracted,
                    "completed_at": datetime.utcnow().isoformat(),
                }
            ).eq("id", str(job_id)).execute()
        )

        logger.info(
            f"Extraction job {job_id} {final_status}. {total_extracted} messages."
        )

    except FloodWaitError as e:
        logger.warning(f"FloodWaitError: sleeping for {e.seconds + 5} seconds.")
        await asyncio.to_thread(
            lambda: supabase.table("extraction_jobs").update(
                {"status": "failed", "error_message": f"FloodWaitError: {e.seconds}s"}
            ).eq("id", str(job_id)).execute()
        )

    except (NotFoundError, ValueError) as e:
        logger.warning(f"Entity not found: {e}")
        error_msg = f"Cannot find the specified channel/group: {e}. "
        error_msg += (
            "Please verify the URL and ensure you have access to this channel. "
        )
        error_msg += "If this is a private channel, ensure you are a member and try restarting your Telegram session."
        await asyncio.to_thread(
            lambda: supabase.table("extraction_jobs").update(
                {
                    "status": "failed",
                    "error_message": error_msg,
                }
            ).eq("id", str(job_id)).execute()
        )

    except Exception as e:
        logger.exception(f"Extraction failed for job {job_id}")
        await asyncio.to_thread(
            lambda: supabase.table("extraction_jobs").update(
                {"status": "failed", "error_message": str(e)}
            ).eq("id", str(job_id)).execute()
        )

    finally:
        # Clean up cancellation event
        cleanup_cancellation_event(job_id)
