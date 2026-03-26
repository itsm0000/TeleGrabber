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
    )
except ImportError:
    # Allows schema tests to import without Telethon installed
    class PhoneCodeExpiredError(Exception): ...
    class PhoneCodeInvalidError(Exception): ...
    class SessionPasswordNeededError(Exception): ...
    class PasswordHashInvalidError(Exception): ...
    class FloodWaitError(Exception): seconds = 0
    class PhoneNumberInvalidError(Exception): ...

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Temporary in-memory store for phone_code_hash — this is short-lived
# (expires within minutes; no need to persist in DB)
_pending_hashes: dict[str, str] = {}  # phone → phone_code_hash


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
        _pending_hashes[phone] = result.phone_code_hash
        logger.info("OTP sent to %s", phone)
        return SendCodeResponse(phone_code_hash=result.phone_code_hash)

    except PhoneNumberInvalidError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid phone number.")
    except FloodWaitError as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Rate limited by Telegram — retry in {exc.seconds}s.",
        )
    except Exception as exc:
        logger.exception("send-code failed for %s", phone)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.post("/verify-code", response_model=AuthStatusResponse)
async def verify_code(body: VerifyCodeRequest) -> AuthStatusResponse:
    """
    Step 2: Submit the OTP received on the phone.

    If the account has 2FA enabled, returns HTTP 202 with
    `{"2fa_required": true}` — the client should then call /verify-2fa.
    """
    phone = body.phone.strip()
    phone_code_hash = body.phone_code_hash or _pending_hashes.get(phone)
    if not phone_code_hash:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "phone_code_hash missing — call /send-code first.",
        )

    try:
        client = await tm_client.get_client(phone)
        await client.sign_in(phone, body.code, phone_code_hash=phone_code_hash)
        await save_session(phone)
        _pending_hashes.pop(phone, None)
        logger.info("Login successful for %s", phone)
        return AuthStatusResponse(phone=phone, authenticated=True, message="Login successful.")

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
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "OTP expired — request a new code.")
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
    try:
        client = await tm_client.get_client(phone)
        await client.sign_in(password=body.password)
        await save_session(phone)
        logger.info("2FA login successful for %s", phone)
        return AuthStatusResponse(phone=phone, authenticated=True, message="2FA login successful.")

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
