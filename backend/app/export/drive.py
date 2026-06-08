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
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google API libraries not installed. Run: pip install google-auth google-auth-oauthlib google-api-python-client",
        ) from exc

    creds_path = settings.google_drive_credentials_json
    if not creds_path or not os.path.exists(creds_path):
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Google Drive credentials are not configured. "
            "Set GOOGLE_DRIVE_CREDENTIALS_JSON in your .env file.",
        )

    import json
    with open(creds_path, "r") as f:
        creds_data = json.load(f)

    SCOPES = ["https://www.googleapis.com/auth/drive"]

    if creds_data.get("type") == "service_account":
        credentials = service_account.Credentials.from_service_account_file(
            creds_path, scopes=SCOPES
        )
    else:
        # OAuth 2.0 Client ID flow for regular user accounts
        token_path = os.path.join(os.path.dirname(creds_path), "token.json")
        credentials = None
        if os.path.exists(token_path):
            credentials = Credentials.from_authorized_user_file(token_path, SCOPES)
        
        if not credentials or not credentials.valid:
            if credentials and credentials.expired and credentials.refresh_token:
                credentials.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(
                    creds_path, SCOPES
                )
                # Opens a browser window locally to authorize
                credentials = flow.run_local_server(port=0)
            # Save the credentials for the next run
            with open(token_path, "w") as token:
                token.write(credentials.to_json())

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


def _generate_folder_name(export_file: Path, job_id: UUID) -> str:
    default_name = f"TeleGrabber — {job_id}"
    try:
        import httpx
        from app.config import settings
        
        if not settings.gemini_api_key:
            return default_name
            
        with open(export_file, "r", encoding="utf-8") as f:
            content = f.read(2000)  # Read first 2000 chars to understand content
            
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={settings.gemini_api_key}"
        payload = {
            "contents": [{
                "parts": [{"text": f"Read this academic material export excerpt and generate a short, intelligent, descriptive folder name for it (3-6 words max, e.g., 'Data Structures Midterm Notes' or 'Physics 101 Lectures'). Return ONLY the folder name, nothing else:\n\n{content}"}]
            }]
        }
        resp = httpx.post(url, json=payload, timeout=10.0)
        resp.raise_for_status()
        data = resp.json()
        folder_name = data["candidates"][0]["content"]["parts"][0]["text"].strip()
        
        # Clean up any quotes or markdown
        folder_name = folder_name.replace('"', '').replace('`', '').strip()
        return folder_name if folder_name else default_name
    except Exception as e:
        logger.error(f"Failed to generate intelligent folder name: {e}")
        return default_name


def upload_job_to_drive(job_id: UUID, export_file: Path) -> tuple[str, str]:
    """
    Upload the export document (and any categorized media) to Google Drive.
    """
    service = _get_drive_service()

    parent_folder_id = settings.google_drive_folder_id or None

    folder_name = _generate_folder_name(export_file, job_id)

    # Create top-level job folder
    job_folder_id = _create_folder(
        service,
        folder_name,
        parent_id=parent_folder_id,
    )
    logger.info("Created Drive folder for job %s: %s", job_id, job_folder_id)

    # Upload main export document
    _upload_file(service, export_file, job_folder_id)
    logger.info("Uploaded export doc: %s", export_file.name)

    # Upload categorized media files (if any)
    from app.db.supabase import get_supabase
    supabase = get_supabase()
    
    category_folder_cache: dict[str, str] = {}
    
    import tempfile
    import httpx
    
    offset = 0
    page_size = 1000
    while True:
        resp = supabase.table("messages").select("media_path, category").eq("job_id", str(job_id)).eq("has_media", True).range(offset, offset + page_size - 1).execute()
        
        if not resp.data:
            break
            
        for row in resp.data:
            media_path = row.get("media_path")
            if not media_path:
                continue
                
            category = row.get("category") or "uncategorized"
            
            # Create category subfolder lazily
            if category not in category_folder_cache:
                cat_folder_id = _create_folder(service, category, parent_id=job_folder_id)
                category_folder_cache[category] = cat_folder_id
                logger.info("Created Drive subfolder: %s", category)

            # Handle remote vs local media
            if media_path.startswith("http"):
                try:
                    # Download to temp file
                    with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(media_path)[1]) as tmp:
                        with httpx.stream("GET", media_path) as stream_resp:
                            stream_resp.raise_for_status()
                            for chunk in stream_resp.iter_bytes(chunk_size=8192):
                                tmp.write(chunk)
                        tmp_path = Path(tmp.name)
                        
                    # Upload and delete
                    _upload_file(service, tmp_path, category_folder_cache[category])
                    tmp_path.unlink(missing_ok=True)
                except Exception as e:
                    logger.error(f"Failed to process remote media {media_path}: {e}")
            else:
                full_path = Path(settings.download_dir) / media_path
                if full_path.exists() and full_path.is_file():
                    _upload_file(service, full_path, category_folder_cache[category])
        
        if len(resp.data) < page_size:
            break
        offset += page_size

    # Build shareable link to the top-level job folder
    drive_link = f"https://drive.google.com/drive/folders/{job_folder_id}"
    return job_folder_id, drive_link
