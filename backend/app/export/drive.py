"""
app/export/drive.py
────────────────────
Google Drive uploader using a service-account JSON credential.

Upload strategy for NotebookLM:
  - Creates one top-level folder per job: "TeleGrabber — {job_id}"
  - Inside, creates per-category subfolders only for categories that have files
  - Uploads the main export doc into the top-level folder
  - Uploads media files into their matching category subfolder

The top-level job folder is created inside GOOGLE_DRIVE_FOLDER_ID (configurable).
Share the top-level folder (or its parent) with your Google account, then add it
as a source in NotebookLM.

Raises HTTPException(503) if credentials are not configured.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException, status

from app.config import settings

logger = logging.getLogger(__name__)

# Lazy-import to avoid hard crash if google libs are not installed
def _get_drive_service():
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google API libraries not installed. Run: pip install google-auth google-api-python-client",
        ) from exc

    creds_path = settings.google_drive_credentials_json
    if not creds_path or not os.path.exists(creds_path):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google Drive credentials are not configured. "
            "Set GOOGLE_DRIVE_CREDENTIALS_JSON in your .env file.",
        )

    credentials = service_account.Credentials.from_service_account_file(
        creds_path,
        scopes=["https://www.googleapis.com/auth/drive"],
    )
    return build("drive", "v3", credentials=credentials, cache_discovery=False)


def _create_folder(service, name: str, parent_id: str | None = None) -> str:
    """Create a Drive folder and return its ID."""
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        meta["parents"] = [parent_id]
    folder = service.files().create(body=meta, fields="id").execute()
    return folder["id"]


def _upload_file(service, local_path: Path, parent_id: str) -> str:
    """Upload a file to Drive and return its file ID."""
    from googleapiclient.http import MediaFileUpload

    mime = "application/octet-stream"
    if local_path.suffix == ".md":
        mime = "text/markdown"
    elif local_path.suffix == ".txt":
        mime = "text/plain"
    elif local_path.suffix == ".zip":
        mime = "application/zip"

    media = MediaFileUpload(str(local_path), mimetype=mime, resumable=True)
    meta = {"name": local_path.name, "parents": [parent_id]}
    file = service.files().create(body=meta, media_body=media, fields="id").execute()
    return file["id"]


def upload_job_to_drive(job_id: UUID, export_file: Path) -> tuple[str, str]:
    """
    Upload the export document (and any categorized media) to Google Drive.

    Structure in Drive:
        {GOOGLE_DRIVE_FOLDER_ID}/
            TeleGrabber — {job_id}/
                export_{job_id}.md
                lecture_notes/   ← only if files exist
                past_exam/
                ...

    Returns:
        (top_level_folder_id, shareable_link)
    """
    service = _get_drive_service()

    parent_folder_id = settings.google_drive_folder_id or None

    # Create top-level job folder
    job_folder_id = _create_folder(
        service,
        f"TeleGrabber — {job_id}",
        parent_id=parent_folder_id,
    )
    logger.info("Created Drive folder for job %s: %s", job_id, job_folder_id)

    # Upload main export document
    _upload_file(service, export_file, job_folder_id)
    logger.info("Uploaded export doc: %s", export_file.name)

    # Upload categorized media files (if any)
    media_dir = Path(settings.download_dir) / str(job_id)
    if media_dir.exists():
        category_folder_cache: dict[str, str] = {}

        for media_file in media_dir.rglob("*"):
            if not media_file.is_file():
                continue

            # Derive category from first path component under media_dir
            try:
                relative_parts = media_file.relative_to(media_dir).parts
                category = relative_parts[0] if len(relative_parts) > 1 else "other"
            except ValueError:
                category = "other"

            # Create category subfolder lazily
            if category not in category_folder_cache:
                cat_folder_id = _create_folder(service, category, parent_id=job_folder_id)
                category_folder_cache[category] = cat_folder_id
                logger.info("Created Drive subfolder: %s", category)

            _upload_file(service, media_file, category_folder_cache[category])

    # Build shareable link to the top-level job folder
    drive_link = f"https://drive.google.com/drive/folders/{job_folder_id}"
    return job_folder_id, drive_link
