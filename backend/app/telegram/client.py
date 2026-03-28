import logging
from telethon import TelegramClient
from telethon.sessions import StringSession
from app.config import settings
from app.db.supabase import get_supabase

logger = logging.getLogger(__name__)

# In-memory store for active clients (phone -> TelegramClient)
_clients: dict[str, TelegramClient] = {}


async def get_client(phone: str) -> TelegramClient:
    """Gets or creates an active TelegramClient for the given phone number."""
    phone = phone.strip()
    if phone in _clients:
        client = _clients[phone]
        if not client.is_connected():
            await client.connect()
        return client

    # Fetch existing session from DB without raising errors if row doesn't exist
    supabase = get_supabase()
    try:
        resp = (
            supabase.table("telegram_sessions")
            .select("session_string")
            .eq("phone", phone)
            .maybe_single()
            .execute()
        )
        session_str = (
            resp.data["session_string"]
            if resp.data and resp.data.get("session_string")
            else ""
        )
    except Exception as exc:
        logger.warning("Could not fetch session for %s: %s", phone, exc)
        session_str = ""
    session = StringSession(session_str)

    client = TelegramClient(
        session, settings.telegram_api_id, settings.telegram_api_hash
    )

    await client.connect()
    _clients[phone] = client
    return client


async def save_session(phone: str, client: TelegramClient | None = None) -> None:
    """Saves the current session string to Supabase.

    Args:
        phone: The phone number associated with the session.
        client: Optional client instance to save. If not provided, looks up
                the client from the internal _clients cache.
    """
    phone = phone.strip()
    target_client = client or _clients.get(phone)
    if target_client:
        session_str = target_client.session.save()
        supabase = get_supabase()
        supabase.table("telegram_sessions").upsert(
            {"phone": phone, "session_string": session_str}
        ).execute()
        logger.debug("Session saved for %s", phone)
    else:
        logger.warning("No client found to save session for %s", phone)


async def is_authorized(phone: str) -> bool:
    """Checks if the client is currently authorized."""
    try:
        client = await get_client(phone)
        return await client.is_user_authorized()
    except Exception as e:
        logger.error(f"Error checking authorization: {e}")
        return False


async def disconnect_all() -> None:
    """Disconnects all active Telethon clients (for app shutdown)."""
    for client in _clients.values():
        if client.is_connected():
            await client.disconnect()
    _clients.clear()


async def clear_session(phone: str) -> None:
    """Clears the session for a given phone number.

    Disconnects the client, removes it from the cache, and deletes
    the session from Supabase. Useful when the session is invalid
    and the user needs to re-authenticate.

    Args:
        phone: The phone number associated with the session to clear.
    """
    phone = phone.strip()
    supabase = get_supabase()

    # Disconnect and remove from cache
    if phone in _clients:
        client = _clients.pop(phone)
        if client.is_connected():
            await client.disconnect()
        logger.info("Disconnected and removed client for %s", phone)

    # Delete session from Supabase
    try:
        supabase.table("telegram_sessions").delete().eq("phone", phone).execute()
        logger.info("Deleted session from database for %s", phone)
    except Exception as exc:
        logger.warning("Could not delete session from database for %s: %s", phone, exc)
