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

        # Add any downloaded media files
        media_dir = Path(settings.download_dir) / str(job_id)
        if media_dir.exists():
            for media_file in media_dir.rglob("*"):
                if media_file.is_file():
                    arcname = Path("media") / media_file.relative_to(media_dir)
                    zf.write(media_file, arcname=str(arcname))

    size = zip_path.stat().st_size
    logger.info("ZIP built: %s (%d bytes)", zip_path, size)
    return zip_path, size
