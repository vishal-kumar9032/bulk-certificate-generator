import re
import secrets
import unicodedata
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional
from email_validator import validate_email, EmailNotValidError
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from app.models import CertificateJob, CertificateItem, JobStatus, ItemStatus
from app.schemas import CertificateJobCreateRequest

# Unambiguous alphabet excluding 0, O, 1, I
UNAMBIGUOUS_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def generate_verification_code() -> str:
    """Generate a unique 8-character verification code in ABCD-EFGH format."""
    p1 = "".join(secrets.choice(UNAMBIGUOUS_ALPHABET) for _ in range(4))
    p2 = "".join(secrets.choice(UNAMBIGUOUS_ALPHABET) for _ in range(4))
    return f"{p1}-{p2}"


def has_control_characters(s: str) -> bool:
    """Check if string contains any control characters."""
    return any(unicodedata.category(ch).startswith("C") for ch in s)


def validate_single_recipient(
    raw_data: Any,
    index: int,
    seen_emails: dict[str, int],
) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Leniently validate a single recipient entry.
    Returns: (cleaned_name, cleaned_email, error_message)
    If error_message is not None, the recipient validation failed.
    """
    if not isinstance(raw_data, dict):
        return None, None, "recipient item must be a JSON object"

    raw_name = raw_data.get("name")
    raw_email = raw_data.get("email")

    # Name validation
    if raw_name is None or (isinstance(raw_name, str) and not raw_name.strip()):
        return None, None, "name is required"
    if not isinstance(raw_name, str):
        return None, None, "name must be a string"

    name_clean = raw_name.strip()
    if len(name_clean) > 100:
        return name_clean, None, "name exceeds 100 characters"
    if has_control_characters(name_clean):
        return name_clean, None, "name contains invalid control characters"

    # Email validation
    if raw_email is None or (isinstance(raw_email, str) and not raw_email.strip()):
        return name_clean, None, "email is required"
    if not isinstance(raw_email, str):
        return name_clean, None, "email must be a string"

    email_clean = raw_email.strip()
    try:
        validated = validate_email(email_clean, check_deliverability=False)
        normalized_email = validated.normalized.lower()
    except (EmailNotValidError, Exception):
        return name_clean, email_clean, "invalid email format"

    # Duplicate check within current request
    if normalized_email in seen_emails:
        first_idx = seen_emails[normalized_email]
        return (
            name_clean,
            normalized_email,
            f"duplicate email in this request (first seen at index {first_idx})",
        )

    # Valid recipient - record in seen emails
    seen_emails[normalized_email] = index
    return name_clean, normalized_email, None


def create_certificate_job(
    db: Session,
    request: CertificateJobCreateRequest,
) -> CertificateJob:
    """
    Create a new CertificateJob and associated CertificateItem records.
    Lenient recipient validation is performed here.
    """
    job_id = str(uuid.uuid4())
    issue_date = request.issue_date or date.today()

    job = CertificateJob(
        id=job_id,
        event_name=request.event_name,
        issuer_name=request.issuer_name,
        issue_date=issue_date,
        total_count=len(request.recipients),
        success_count=0,
        failed_count=0,
        status=JobStatus.PENDING,
    )
    db.add(job)

    seen_emails: dict[str, int] = {}
    failed_initial_count = 0

    items_to_add: list[CertificateItem] = []
    for idx, raw_rec in enumerate(request.recipients):
        name, email, err_msg = validate_single_recipient(raw_rec, idx, seen_emails)
        item_id = str(uuid.uuid4())

        if err_msg:
            # Validation failure: immediately marked FAILED with explanation
            item = CertificateItem(
                id=item_id,
                job_id=job_id,
                index=idx,
                recipient_name=name,
                recipient_email=email,
                status=ItemStatus.FAILED,
                error_message=err_msg,
                completed_at=datetime.now(timezone.utc),
            )
            failed_initial_count += 1
        else:
            # Valid recipient: ready for PDF rendering
            v_code = generate_verification_code()
            item = CertificateItem(
                id=item_id,
                job_id=job_id,
                index=idx,
                recipient_name=name,
                recipient_email=email,
                status=ItemStatus.PENDING,
                verification_code=v_code,
            )

        items_to_add.append(item)

    db.add_all(items_to_add)
    job.failed_count = failed_initial_count

    # If every recipient failed upfront validation, mark job as FAILED immediately
    if failed_initial_count == len(request.recipients):
        job.status = JobStatus.FAILED
        job.completed_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(job)
    return job


def get_job_by_id(db: Session, job_id: str) -> Optional[CertificateJob]:
    """Retrieve a job by its UUID."""
    stmt = select(CertificateJob).where(CertificateJob.id == job_id)
    return db.execute(stmt).scalar_one_or_none()


def get_job_items(
    db: Session,
    job_id: str,
    limit: int = 50,
    offset: int = 0,
    status_filter: Optional[ItemStatus] = None,
) -> tuple[int, list[CertificateItem]]:
    """Retrieve paginated certificate items for a job with optional status filter."""
    count_stmt = select(func.count(CertificateItem.id)).where(CertificateItem.job_id == job_id)
    if status_filter:
        count_stmt = count_stmt.where(CertificateItem.status == status_filter)
    total = db.execute(count_stmt).scalar() or 0

    items_stmt = (
        select(CertificateItem)
        .where(CertificateItem.job_id == job_id)
        .order_by(CertificateItem.index)
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        items_stmt = items_stmt.where(CertificateItem.status == status_filter)

    items = db.execute(items_stmt).scalars().all()
    return total, list(items)


def get_item_by_id(db: Session, job_id: str, item_id: str) -> Optional[CertificateItem]:
    """Retrieve an item by ID belonging to a specific job."""
    stmt = select(CertificateItem).where(
        CertificateItem.id == item_id,
        CertificateItem.job_id == job_id,
    )
    return db.execute(stmt).scalar_one_or_none()


def get_item_by_verification_code(db: Session, code: str) -> Optional[CertificateItem]:
    """Retrieve a successfully generated certificate item by verification code."""
    stmt = (
        select(CertificateItem)
        .where(
            CertificateItem.verification_code == code,
            CertificateItem.status == ItemStatus.SUCCESS,
        )
    )
    return db.execute(stmt).scalar_one_or_none()
