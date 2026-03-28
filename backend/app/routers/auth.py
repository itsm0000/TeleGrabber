"""
routers/auth.py
───────────────
FastAPI router for Telegram MTProto authentication.

Flow:
  POST /api/auth/send-code    → sends OTP to phone via Telegram
  POST /api/auth/verify-code  → validates OTP; raises 2FA flag if needed
  POST /api/auth/verify-2fa   → submits cloud password for 2FA accounts
  GET  /api/auth/status       → checks if a phone session is already authorized
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from telethon import TelegramClient

from app.models.schemas import (
    AuthStatusResponse,
    SendCodeRequest,
    SendCodeResponse,
    Verify2FARequest,
    VerifyCodeRequest,
)
from app.telegram import client as tm_client
from app.telegram.client import save_session

try:
    from telethon.errors import (
        PhoneCodeExpiredError,
        PhoneCodeInvalidError,
        SessionPasswordNeededError,
        PasswordHashInvalidError,
        FloodWaitError,
        PhoneNumberInvalidError,
        AuthKeyError,
        SessionRevokedError,
    )
except ImportError:
    # Allows schema tests to import without Telethon installed
    class PhoneCodeExpiredError(Exception): ...

    class PhoneCodeInvalidError(Exception): ...

    class SessionPasswordNeededError(Exception): ...

    class PasswordHashInvalidError(Exception): ...

    class FloodWaitError(Exception):
        seconds = 0

    class PhoneNumberInvalidError(Exception): ...

    class AuthKeyError(Exception): ...

    class SessionRevokedError(Exception): ...


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Temporary in-memory store for phone_code_hash and client — this is short-lived
# (expires within minutes; no need to persist in DB)
# CRITICAL: Must store the same client instance that generated the phone_code_hash,
# as the hash is bound to that specific client session.
_pending_hashes: dict[
    str, tuple[str, TelegramClient]
] = {}  # phone → (phone_code_hash, client)


@router.post("/send-code", response_model=SendCodeResponse)
async def send_code(body: SendCodeRequest) -> SendCodeResponse:
    """
    Step 1: Initiate login — send an OTP to the phone number via Telegram.

    Returns the `phone_code_hash` the client must echo back in verify-code.
    """
    phone = body.phone.strip()
    try:
        client = await tm_client.get_client(phone)

        # If already authorized, skip OTP entirely
        if await client.is_user_authorized():
            return SendCodeResponse(
                phone_code_hash="ALREADY_AUTHORIZED",
                message="Session already active — no OTP needed.",
            )

        result = await client.send_code_request(phone)
        _pending_hashes[phone] = (result.phone_code_hash, client)
        logger.info("OTP sent to %s (hash bound to client at %s)", phone, id(client))
        return SendCodeResponse(phone_code_hash=result.phone_code_hash)

    except PhoneNumberInvalidError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid phone number.")
    except FloodWaitError as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Rate limited by Telegram — retry in {exc.seconds}s.",
        )
    except (AuthKeyError, SessionRevokedError) as exc:
        # Session is invalid/corrupted — user needs to clear and re-authenticate
        logger.warning("Session invalid for %s: %s", phone, exc)
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Session expired or invalid. Call /api/auth/clear-session to reset and try again.",
        )
    except Exception as exc:
        logger.exception("send-code failed for %s", phone)
        # Check if the error message indicates an invalid session
        error_str = str(exc).lower()
        if "no valid" in error_str or "session" in error_str:
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "Session expired or invalid. Call /api/auth/clear-session to reset and try again.",
            )
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.post("/verify-code", response_model=AuthStatusResponse)
async def verify_code(body: VerifyCodeRequest) -> AuthStatusResponse:
    """
    Step 2: Submit the OTP received on the phone.

    If the account has 2FA enabled, returns HTTP 202 with
    `{"2fa_required": true}` — the client should then call /verify-2fa.
    """
    phone = body.phone.strip()

    # Retrieve the pending hash and the EXACT client that generated it
    pending = _pending_hashes.get(phone)
    if not pending:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "phone_code_hash missing — call /send-code first.",
        )

    phone_code_hash, client = pending
    logger.debug("Using client %s for verify_code on %s", id(client), phone)

    try:
        await client.sign_in(phone, body.code, phone_code_hash=phone_code_hash)
        await save_session(phone, client)
        _pending_hashes.pop(phone, None)
        logger.info("Login successful for %s", phone)
        return AuthStatusResponse(
            phone=phone, authenticated=True, message="Login successful."
        )

    except SessionPasswordNeededError:
        # Account has 2FA — tell the frontend to show the password field
        return AuthStatusResponse(
            phone=phone,
            authenticated=False,
            message="2FA_REQUIRED",
        )
    except PhoneCodeInvalidError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid OTP code.")
    except PhoneCodeExpiredError:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "OTP expired — request a new code."
        )
    except Exception as exc:
        logger.exception("verify-code failed for %s", phone)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.post("/verify-2fa", response_model=AuthStatusResponse)
async def verify_2fa(body: Verify2FARequest) -> AuthStatusResponse:
    """
    Step 3 (conditional): Submit the Telegram cloud password for 2FA accounts.
    Only needed if /verify-code returns `"message": "2FA_REQUIRED"`.
    """
    phone = body.phone.strip()

    # After verify-code, the client should still be in _pending_hashes
    # We need the same client that was partially authenticated
    pending = _pending_hashes.get(phone)
    if not pending:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "No pending session — call /verify-code first.",
        )

    _, client = pending
    logger.debug("Using client %s for verify_2fa on %s", id(client), phone)

    try:
        await client.sign_in(password=body.password)
        await save_session(phone, client)
        _pending_hashes.pop(phone, None)  # Clear after successful 2FA
        logger.info("2FA login successful for %s", phone)
        return AuthStatusResponse(
            phone=phone, authenticated=True, message="2FA login successful."
        )

    except PasswordHashInvalidError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Incorrect 2FA password.")
    except Exception as exc:
        logger.exception("verify-2fa failed for %s", phone)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.get("/status", response_model=AuthStatusResponse)
async def auth_status(phone: str) -> AuthStatusResponse:
    """
    Check whether an existing session for *phone* is still valid.
    Safe to call on app load to skip the login flow.
    """
    phone = phone.strip()
    authorized = await tm_client.is_authorized(phone)
    return AuthStatusResponse(
        phone=phone,
        authenticated=authorized,
        message="Session active." if authorized else "Not authenticated.",
    )


@router.post("/clear-session")
async def clear_session(phone: str) -> dict:
    """
    Clear the session for a given phone number.

    Use this when the session is invalid (e.g., "no valid old session" error)
    and the user needs to re-authenticate from scratch.
    """
    phone = phone.strip()
    # Clear any pending hash for this phone
    _pending_hashes.pop(phone, None)
    # Clear the session from cache and database
    await tm_client.clear_session(phone)
    return {"message": "Session cleared.", "phone": phone}
