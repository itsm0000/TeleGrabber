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
    resp = supabase.table("telegram_sessions").select("session_string").eq("phone", phone).maybe_single().execute()
    
    session_str = resp.data["session_string"] if resp.data else ""
    session = StringSession(session_str)
    
    client = TelegramClient(
        session,
        settings.telegram_api_id,
        settings.telegram_api_hash
    )
    
    await client.connect()
    _clients[phone] = client
    return client

async def save_session(phone: str) -> None:
    """Saves the current session string to Supabase."""
    phone = phone.strip()
    if phone in _clients:
        client = _clients[phone]
        session_str = client.session.save()
        supabase = get_supabase()
        supabase.table("telegram_sessions").upsert({
            "phone": phone,
            "session_string": session_str
        }).execute()

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
