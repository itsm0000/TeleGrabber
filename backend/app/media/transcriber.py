"""
media/transcriber.py
────────────────────
Voice note transcription — Whisper-tiny integration.

Default: stub mode (returns None immediately).
Enable with `ENABLE_WHISPER=true` in .env and install openai-whisper:
    pip install openai-whisper torch
"""
from __future__ import annotations

import logging
from typing import Optional

from app.config import settings

logger = logging.getLogger(__name__)

# Lazy-load Whisper to avoid import errors when not installed
_whisper_model = None


async def transcribe_voice(file_path: str) -> Optional[str]:
    """
    Transcribe a voice note at *file_path* using Whisper.

    Returns the transcribed text, or None if transcription is disabled /
    unavailable / fails.
    """
    if not settings.enable_whisper:
        return None

    try:
        model = _load_whisper_model()
        if model is None:
            return None

        # Whisper is CPU-bound — run in a thread pool to avoid blocking the
        # async event loop
        import asyncio
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: model.transcribe(file_path, fp16=False),
        )
        transcript: str = result.get("text", "").strip()
        logger.info("Transcribed voice note: %d chars", len(transcript))
        return transcript or None

    except Exception as exc:
        logger.warning("Whisper transcription failed for %s: %s", file_path, exc)
        return None


def _load_whisper_model():
    """Load (and cache) the Whisper model specified in settings."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    try:
        import whisper  # openai-whisper
        logger.info("Loading Whisper model: %s", settings.whisper_model)
        _whisper_model = whisper.load_model(settings.whisper_model)
        return _whisper_model
    except ImportError:
        logger.warning(
            "openai-whisper not installed. "
            "Run: pip install openai-whisper torch"
        )
        return None
