"""
app/export/zip_builder.py
──────────────────────────
Creates a ZIP archive bundling the export file and any downloaded media
for a job, ready for local download or Google Drive upload.

Archive structure:
  export_{job_id}.zip
  ├── export_{job_id}.md   (or .txt)
  └── media/               (if download_dir/{job_id}/ exists)
      ├── lecture_notes/
      ├── past_exam/
      └── ...
"""
from __future__ import annotations

import logging
import zipfile
from pathlib import Path
from uuid import UUID

from app.config import settings

logger = logging.getLogger(__name__)


def build_zip(job_id: UUID, export_file: Path) -> tuple[Path, int]:
    """
    Package the export file and all downloaded media into a ZIP.

    Args:
        job_id:      The extraction job UUID.
        export_file: Path to the already-generated .md or .txt file.

    Returns:
        (zip_path, size_in_bytes)
    """
    out_dir = Path(settings.export_dir) / str(job_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"export_{job_id}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add the main export document
        zf.write(export_file, arcname=export_file.name)

        # Query database to find all media paths associated with this job
        from app.db.supabase import get_supabase
        import httpx
        import tempfile
        import os
        supabase = get_supabase()
        
        # Paginate through messages to find all media paths
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
                
                if media_path.startswith("http"):
                    filename = os.path.basename(media_path.split("?")[0])
                    arcname = f"media/{category}/{filename}"
                    if arcname not in zf.namelist():
                        try:
                            # Stream the file from Supabase
                            with httpx.stream("GET", media_path) as stream_resp:
                                stream_resp.raise_for_status()
                                with tempfile.NamedTemporaryFile(delete=False) as tmp:
                                    for chunk in stream_resp.iter_bytes(chunk_size=8192):
                                        tmp.write(chunk)
                                    tmp_path = Path(tmp.name)
                                
                                zf.write(tmp_path, arcname=arcname)
                                tmp_path.unlink(missing_ok=True)
                        except Exception as e:
                            logger.error(f"Failed to zip remote media {media_path}: {e}")
                else:
                    full_path = Path(settings.download_dir) / media_path
                    if full_path.exists() and full_path.is_file():
                        # Organize by category in the ZIP if a category exists
                        # media_path often has the chat_id prefix (e.g. "12345/10.jpg"), just use the filename
                        arcname = f"media/{category}/{full_path.name}"
                        # Don't add the same file twice if somehow queried multiple times
                        if arcname not in zf.namelist():
                            zf.write(full_path, arcname=arcname)
            
            if len(resp.data) < page_size:
                break
            offset += page_size

    size = zip_path.stat().st_size
    logger.info("ZIP built: %s (%d bytes)", zip_path, size)
    return zip_path, size
