"""
routers/extract.py
──────────────────
FastAPI router for link parsing and extraction job management.

Endpoints:
  POST /api/extract/parse-link      → parse a Telegram URL
  POST /api/extract/start           → create a job and start async extraction
  POST /api/extract/{job_id}/stop   → stop a running extraction job
  GET  /api/extract/{job_id}/status → poll job progress
  GET  /api/extract/{job_id}/results → paginated list of extracted messages
"""

from __future__ import annotations

import json
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
    StopExtractionResponse,
)
from app.telegram.client import get_client, is_authorized
from app.telegram.extractor import run_extraction, cancel_job
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


@router.post(
    "/start",
    response_model=StartExtractionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
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
    effective_max_messages = body.max_messages
    if body.filters and body.filters.max_messages is not None:
        effective_max_messages = body.filters.max_messages
    job_data = {
        "phone": phone,
        "source_url": body.url,
        "entity_ref": parsed.entity_ref,
        "topic_id": parsed.topic_id,
        "link_type": parsed.link_type,
        "status": "pending",
        "max_messages": effective_max_messages,
        "filters_json": body.filters.json() if body.filters else None,
    }
    try:
        job_row = supabase.table("extraction_jobs").insert(job_data).execute()
    except Exception as e:
        # If error is about unknown column 'filters_json', retry without it
        if "filters_json" in str(e):
            job_data.pop("filters_json", None)
            job_row = supabase.table("extraction_jobs").insert(job_data).execute()
        else:
            raise

    if not job_row.data:
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create extraction job."
        )

    job_id = UUID(job_row.data[0]["id"])
    client = await get_client(phone)

    # ── Fire and forget ───────────────────────────────────────────────────────
    background_tasks.add_task(
        run_extraction,
        job_id=job_id,
        client=client,
        entity_ref=parsed.entity_ref,
        topic_id=parsed.topic_id,
        max_messages=effective_max_messages,
        filters=body.filters,
    )
    logger.info("Extraction job %s created for %s", job_id, body.url)
    return StartExtractionResponse(job_id=job_id)


@router.post("/{job_id}/stop", response_model=StopExtractionResponse)
async def stop_extraction(job_id: UUID) -> StopExtractionResponse:
    """Stop a running extraction job."""
    # Check if job exists and is running
    supabase = get_supabase()
    resp = (
        supabase.table("extraction_jobs")
        .select("id, status, message_count")
        .eq("id", str(job_id))
        .maybe_single()
        .execute()
    )

    if not resp.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")

    row = resp.data
    if row["status"] not in ("pending", "running"):
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"Cannot stop job with status '{row['status']}'. Only pending/running jobs can be stopped.",
        )

    # Signal cancellation
    if not cancel_job(job_id):
        # The job is a zombie from a previous restart. Force stop in DB.
        supabase.table("extraction_jobs").update({"status": "stopped"}).eq("id", str(job_id)).execute()

    return StopExtractionResponse(
        job_id=job_id,
        status="stopped",
        message_count=row["message_count"],
    )


@router.get("/{job_id}/status", response_model=JobStatusResponse)
async def job_status(job_id: UUID) -> JobStatusResponse:
    """Poll the status and message count of an extraction job."""
    supabase = get_supabase()
    resp = (
        supabase.table("extraction_jobs")
        .select(
            "id, status, message_count, error_message, started_at, completed_at, max_messages, filters_json"
        )
        .eq("id", str(job_id))
        .maybe_single()
        .execute()
    )
    if not resp.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found.")

    row = resp.data
    filters_json_raw = row.get("filters_json")
    filters_json_dict = None
    if filters_json_raw:
        if isinstance(filters_json_raw, str):
            try:
                filters_json_dict = json.loads(filters_json_raw)
            except json.JSONDecodeError:
                filters_json_dict = {}
        elif isinstance(filters_json_raw, dict):
            filters_json_dict = filters_json_raw

    return JobStatusResponse(
        job_id=UUID(row["id"]),
        status=row["status"],
        message_count=row["message_count"],
        error_message=row.get("error_message"),
        started_at=row.get("started_at"),
        completed_at=row.get("completed_at"),
        max_messages=row.get("max_messages"),
        filters_json=filters_json_dict,
    )


@router.get("/{job_id}/results", response_model=JobResultsResponse)
async def job_results(
    job_id: UUID,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=100, ge=1, le=500),
    category: str = Query(default=None),
) -> JobResultsResponse:
    """
    Return paginated extracted messages for a completed job.
    Default page size: 100. Max: 500.
    Optionally filter by `category` for server-side category filtering.
    """
    supabase = get_supabase()

    total = 0
    if not category:
        # Avoid exact count on large tables if no filter is applied
        job_resp = supabase.table("extraction_jobs").select("message_count").eq("id", str(job_id)).maybe_single().execute()
        if job_resp.data:
            total = job_resp.data.get("message_count") or 0
    else:
        # Count total rows for filtered result
        count_q = supabase.table("messages").select("id", count="exact").eq("job_id", str(job_id))
        if category:
            count_q = count_q.eq("category", category)
        count_resp = count_q.execute()
        total = count_resp.count or 0

    # Paginated fetch, ordered by Telegram message timestamp
    offset = (page - 1) * page_size
    
    q = supabase.table("messages").select("*").eq("job_id", str(job_id))
    if category:
        q = q.eq("category", category)
        
    rows_resp = (
        q
        .order("date", desc=False)
        .range(offset, offset + page_size - 1)
        .execute()
    )

    messages = [ExtractedMessageOut(**row) for row in (rows_resp.data or [])]
    return JobResultsResponse(job_id=job_id, total=total, messages=messages)
