import re
import tempfile
import zipfile
from pathlib import Path
from sqlalchemy.orm import Session
from app.models import CertificateItem, ItemStatus
from app.services.job_service import get_job_items
from app.settings import settings


def sanitize_filename(name: str) -> str:
    """Sanitize recipient name for safe inclusion in filenames."""
    if not name:
        return "certificate"
    # Convert to lowercase and replace non-alphanumeric chars with hyphens
    sanitized = re.sub(r"[^a-zA-Z0-9]+", "-", name.strip().lower()).strip("-")
    return sanitized if sanitized else "certificate"


def create_job_zip(db: Session, job_id: str) -> Path:
    """
    Build a ZIP file containing all successful certificates for a job.
    Returns the Path to a temporary zip file.
    Raises ValueError if no successful certificates exist.
    """
    # Fetch all SUCCESS items for the job
    _, items = get_job_items(db, job_id=job_id, limit=10000, offset=0, status_filter=ItemStatus.SUCCESS)

    if not items:
        raise ValueError("No successful certificates available to download for this job")

    # Create temporary file for ZIP
    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_zip.close()
    temp_zip_path = Path(temp_zip.name)

    with zipfile.ZipFile(temp_zip_path, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in items:
            if not item.file_path:
                continue
            abs_path = settings.STORAGE_DIR / item.file_path
            if not abs_path.exists():
                continue

            safe_name = sanitize_filename(item.recipient_name or "recipient")
            # Format filename as e.g. 0001_asha-verma.pdf
            arcname = f"{item.index + 1:04d}_{safe_name}.pdf"
            zf.write(abs_path, arcname=arcname)

    return temp_zip_path
