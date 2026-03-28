"""
routers/export.py
──────────────────
FastAPI router for the AI categorization and export pipeline.

Endpoints:
  POST /api/export/categorize       → run Gemini category tagger on a job's messages
  POST /api/export/generate         → generate .md or .txt export document
  GET  /api/export/{job_id}/download → stream ZIP archive as file download
  POST /api/export/drive-upload     → upload job export to Google Drive
"""
from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import FileResponse

from app.ai.categorizer import categorize_job
from app.ai.formatter import generate_export
from app.export.drive import upload_job_to_drive
from app.export.zip_builder import build_zip
from app.models.schemas import (
    CategorizeRequest,
    CategorizeResponse,
    DriveUploadRequest,
    DriveUploadResponse,
    ExportRequest,
    ExportResponse,
)
from app.config import settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/export", tags=["export"])


@router.post("/categorize", response_model=CategorizeResponse)
async def categorize(body: CategorizeRequest) -> CategorizeResponse:
    """
    Run Gemini 2.0 Flash over all uncategorized messages for the given job.
    Tags each message with one of 8 academic category labels and writes
    the result back to Supabase.
    """
    try:
        count = await categorize_job(body.job_id)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))
    except Exception as exc:
        logger.exception("Categorization failed for job %s", body.job_id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    return CategorizeResponse(job_id=body.job_id, categories_written=count)


@router.post("/generate", response_model=ExportResponse)
async def generate(body: ExportRequest) -> ExportResponse:
    """
    Generate a structured export document (.md or .txt) from categorized messages.
    The file is stored server-side and its metadata is returned.
    Use GET /api/export/{job_id}/download to retrieve the ZIP.
    """
    try:
        file_path, size = generate_export(body.job_id, fmt=body.format)
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc))
    except Exception as exc:
        logger.exception("Export generation failed for job %s", body.job_id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    return ExportResponse(
        job_id=body.job_id,
        filename=file_path.name,
        size_bytes=size,
    )


@router.get("/{job_id}/download")
async def download_zip(job_id: UUID):
    """
    Build (or return cached) ZIP archive for the job and stream it as a download.
    Includes the export document and all downloaded media files.
    """
    out_dir = Path(settings.export_dir) / str(job_id)
    # Look for any already-generated export doc in this folder
    candidates = list(out_dir.glob(f"export_{job_id}.*")) if out_dir.exists() else []
    export_file = next(
        (p for p in candidates if p.suffix in (".md", ".txt")), None
    )

    if not export_file:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No export file found for this job. Call POST /api/export/generate first.",
        )

    try:
        zip_path, _ = build_zip(job_id, export_file)
    except Exception as exc:
        logger.exception("ZIP build failed for job %s", job_id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    return FileResponse(
        path=str(zip_path),
        filename=zip_path.name,
        media_type="application/zip",
    )


@router.post("/drive-upload", response_model=DriveUploadResponse)
async def drive_upload(body: DriveUploadRequest) -> DriveUploadResponse:
    """
    Upload the job export to Google Drive.
    Creates a per-job folder with per-category subfolders inside
    the configured GOOGLE_DRIVE_FOLDER_ID.

    Requires GOOGLE_DRIVE_CREDENTIALS_JSON to be set in .env.
    Returns HTTP 503 if Drive credentials are not configured.
    """
    out_dir = Path(settings.export_dir) / str(body.job_id)
    candidates = list(out_dir.glob(f"export_{body.job_id}.*")) if out_dir.exists() else []
    export_file = next(
        (p for p in candidates if p.suffix in (".md", ".txt")), None
    )

    if not export_file:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            "No export file found for this job. Call POST /api/export/generate first.",
        )

    try:
        folder_id, drive_link = upload_job_to_drive(body.job_id, export_file)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Drive upload failed for job %s", body.job_id)
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(exc))

    return DriveUploadResponse(
        job_id=body.job_id,
        drive_folder_id=folder_id,
        drive_link=drive_link,
    )
