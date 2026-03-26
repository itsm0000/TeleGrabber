"""
telegram/parser.py
──────────────────
Parse any Telegram URL into a structured ParsedLink.

Supported formats:
  https://t.me/username               → public_channel
  https://t.me/c/1234567890/99        → private_chat  (optional msg_id)
  https://t.me/c/1234567890/99?topic=5678  → topic_thread
  https://t.me/joinchat/HASH          → invite_link
  https://t.me/+HASH                  → invite_link (newer format)
"""
from __future__ import annotations

import re
from urllib.parse import urlparse, parse_qs

from app.models.schemas import ParsedLinkResponse, LinkType


# Pre-compiled patterns
_PUBLIC_PATTERN = re.compile(
    r"^t\.me/(?P<username>[a-zA-Z][a-zA-Z0-9_]{3,})(?:/(?P<msg_id>\d+))?$"
)
_PRIVATE_PATTERN = re.compile(
    r"^t\.me/c/(?P<chat_id>\d+)/(?P<msg_id>\d+)$"
)
_INVITE_HASH = re.compile(
    r"^t\.me/(?:joinchat/|\+)(?P<hash>[A-Za-z0-9_-]+)$"
)


def parse_telegram_link(url: str) -> ParsedLinkResponse:
    """
    Parse a Telegram URL and return a ParsedLinkResponse.

    Raises ValueError if the URL cannot be parsed.
    """
    # Normalise: strip scheme, www, trailing slashes
    cleaned = url.strip().rstrip("/")
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = re.sub(r"^www\.", "", cleaned)

    # ── Invite link (t.me/joinchat/HASH or t.me/+HASH) ───────────────────────
    invite_m = _INVITE_HASH.match(cleaned)
    if invite_m:
        return ParsedLinkResponse(
            original_url=url,
            link_type="invite_link",
            entity_ref=cleaned,
            invite_hash=invite_m.group("hash"),
        )

    # ── Private chat / topic thread (t.me/c/CHATID/MSGID?topic=ID) ───────────
    # Parse query string before regex (regex matches path only)
    path_part = cleaned.split("?")[0]
    qs = parse_qs(urlparse(f"https://{cleaned}").query)
    topic_id: int | None = None
    if "topic" in qs:
        try:
            topic_id = int(qs["topic"][0])
        except (ValueError, IndexError):
            pass

    private_m = _PRIVATE_PATTERN.match(path_part)
    if private_m:
        chat_id = private_m.group("chat_id")
        msg_id = int(private_m.group("msg_id"))
        # Private chats in Telegram always have a -100 prefix for Telethon
        entity_ref = f"-100{chat_id}"
        link_type: LinkType = "topic_thread" if topic_id else "private_chat"
        return ParsedLinkResponse(
            original_url=url,
            link_type=link_type,
            entity_ref=entity_ref,
            msg_id=msg_id,
            topic_id=topic_id,
        )

    # ── Public channel / group (t.me/username) ────────────────────────────────
    public_m = _PUBLIC_PATTERN.match(path_part)
    if public_m:
        username = public_m.group("username")
        msg_id_str = public_m.group("msg_id")
        return ParsedLinkResponse(
            original_url=url,
            link_type="public_channel",
            entity_ref=f"@{username}",
            msg_id=int(msg_id_str) if msg_id_str else None,
            topic_id=topic_id,  # allow ?topic= on public URLs too
        )

    raise ValueError(
        f"Unrecognised Telegram URL format: {url}\n"
        "Supported formats: t.me/username, t.me/c/CHATID/MSGID, "
        "t.me/c/CHATID/MSGID?topic=ID, t.me/joinchat/HASH, t.me/+HASH"
    )
