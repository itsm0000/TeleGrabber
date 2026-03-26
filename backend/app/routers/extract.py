"""
routers/extract.py
──────────────────
FastAPI router for link parsing and extraction job management.

Endpoints:
  POST /api/extract/parse-link      → parse a Telegram URL
  POST /api/extract/start           → create a job and start async extraction
  GET  /api/extract/{job_id}/status → poll job progress
  GET  /api/extract/{job_id}/results → paginated list of extracted messages
"""
from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status

from app.db.supabase import get_supabase
from app.models.schemas import (
    ExtractedMessageOut,
    JobResultsResponse,
    JobStatusResponse,
    ParseLinkRequest,
    ParsedLinkResponse,
    StartExtractionRequest,
    StartExtractionResponse,
)
from app.telegram.client import get_client, is_authorized
from app.telegram.extractor import run_extraction
from app.telegram.parser import parse_telegram_link

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/extract", tags=["extraction"])


@router.post("/parse-link", response_model=ParsedLinkResponse)
async def parse_link(body: ParseLinkRequest) -> ParsedLinkResponse:
    """Parse a Telegram URL and return its structural components."""
    try:
        return parse_telegram_link(body.url)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))


@router.post("/start", response_model=StartExtractionResponse, status_code=status.HTTP_202_ACCEPTED)
async def start_extraction(
    body: StartExtractionRequest,
    background_tasks: BackgroundTasks,
) -> StartExtractionResponse:
    """
    Parse the given Telegram URL, create an extraction_jobs row in Supabase,
    and kick off the async extraction loop in the background.
    """
    phone = body.phone.strip()

    # ── Guard: require authenticated session ──────────────────────────────────
    if not await is_authorized(phone):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Phone not authenticated — complete the auth flow first.",
        )

    # ── Parse link ────────────────────────────────────────────────────────────
    try:
        parsed = parse_telegram_link(body.url)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc))

    # ── Create job row ────────────────────────────────────────────────────────
    supabase = get_supabase()
    job_row = (
        supabase.table("extraction_jobs")
        .insert({
            "phone": phone,
            "source_url": body.url,
            "entity_ref": parsed.entity_ref,
            "topic_id": parsed.topic_id,
            "link_type": parsed.link_type,
            "status": "pending",
        })
        .execute()
    )

    if not job_row.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create extraction job.")

    job_id = UUID(job_row.data[0]["id"])
    client = await get_client(phone)

    # ── Fire and forget ───────────────────────────────────────────────────────
    background_tasks.add_task(
        run_extraction,
        job_id=job_id,
        client=client,
        entity_ref=parsed.entity_ref,
        topic_id=parsed.topic_id,
    )
    logger.info("Extraction job %s created for %s", job_id, body.url)
    return StartExtractionResponse(job_id=job_id)


@router.get("/{job_id}/status", response_model=JobStatusResponse)
async def job_status(job_id: UUID) -> JobStatusResponse:
    """Poll the status and message count of an extraction job."""
    supabase = get_supabase()
    resp = (
        supabase.table("extraction_jobs")
        .select("id, status, message_count, error_message, started_at, completed_at")
        .eq("id", str(job_id))
        .maybe_single()
        .execute()
    )
    if not resp.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")

    row = resp.data
    return JobStatusResponse(
        job_id=UUID(row["id"]),
        status=row["status"],
        message_count=row["message_count"],
        error_message=row.get("error_message"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
    )


@router.get("/{job_id}/results", response_model=JobResultsResponse)
async def job_results(
    job_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
) -> JobResultsResponse:
    """
    Return paginated extracted messages for a completed job.
    Default page size: 100. Max: 500.
    """
    supabase = get_supabase()

    # Count total rows
    count_resp = (
        supabase.table("messages")
        .select("id", count="exact")
        .eq("job_id", str(job_id))
        .execute()
    )
    total = count_resp.count or 0

    # Paginated fetch, ordered by Telegram message timestamp
    offset = (page - 1) * page_size
    rows_resp = (
        supabase.table("messages")
        .select("*")
        .eq("job_id", str(job_id))
        .order("date", desc=False)
        .range(offset, offset + page_size - 1)
        .execute()
    )

    messages = [ExtractedMessageOut(**row) for row in (rows_resp.data or [])]
    return JobResultsResponse(job_id=job_id, total=total, messages=messages)
