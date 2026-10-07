import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from sqlalchemy import select, func
from sqlalchemy.orm import Session

from app.database import get_db_session
from app.models import CertificateJob, CertificateItem, JobStatus, ItemStatus
from app.services.certificate_renderer import render_certificate, CertificateData
from app.settings import settings

logger = logging.getLogger(__name__)

# Module-level worker executor, initialized during app lifespan
_executor: Optional[ThreadPoolExecutor] = None


def init_executor(max_workers: int) -> ThreadPoolExecutor:
    """Initialize the background ThreadPoolExecutor."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="cert_worker_",
        )
        logger.info("Initialized ThreadPoolExecutor with %d workers", max_workers)
    return _executor


def shutdown_executor() -> None:
    """Gracefully shutdown the background ThreadPoolExecutor."""
    global _executor
    if _executor is not None:
        logger.info("Shutting down ThreadPoolExecutor...")
        _executor.shutdown(wait=True)
        _executor = None
        logger.info("ThreadPoolExecutor shut down successfully.")


def get_executor() -> Optional[ThreadPoolExecutor]:
    """Get the active ThreadPoolExecutor."""
    return _executor


def process_single_item(
    session: Session,
    item_id: str,
    event_name: str,
    issuer_name: Optional[str],
    issue_date: str,
) -> None:
    """
    Process an individual certificate item within its own transaction.
    Any failure during rendering is isolated and committed to the database.
    """
    item = session.execute(
        select(CertificateItem).where(CertificateItem.id == item_id)
    ).scalar_one_or_none()

    if not item:
        return

    # Skip already completed items (idempotency)
    if item.status == ItemStatus.SUCCESS:
        return

    # Check recipient name
    if not item.recipient_name:
        item.status = ItemStatus.FAILED
        item.error_message = "name is missing or invalid"
        item.completed_at = datetime.now(timezone.utc)
        session.commit()
        return

    rel_path = f"{item.job_id}/{item.id}.pdf"
    abs_path = settings.STORAGE_DIR / rel_path

    try:
        cert_data = CertificateData(
            recipient_name=item.recipient_name,
            event_name=event_name,
            issue_date=issue_date,
            issuer_name=issuer_name,
            verification_code=item.verification_code,
        )
        render_certificate(cert_data, abs_path)

        item.file_path = rel_path
        item.status = ItemStatus.SUCCESS
        item.error_message = None
        item.completed_at = datetime.now(timezone.utc)
    except Exception as exc:
        logger.exception("Error rendering certificate item %s: %s", item.id, exc)
        item.status = ItemStatus.FAILED
        item.error_message = f"Generation error: {str(exc)}"
        item.completed_at = datetime.now(timezone.utc)

    session.commit()


def update_job_progress(session: Session, job_id: str) -> None:
    """Update success and failed counters for a job based on current DB state."""
    job = session.execute(
        select(CertificateJob).where(CertificateJob.id == job_id)
    ).scalar_one_or_none()

    if not job:
        return

    success_cnt = session.execute(
        select(func.count(CertificateItem.id)).where(
            CertificateItem.job_id == job_id,
            CertificateItem.status == ItemStatus.SUCCESS,
        )
    ).scalar() or 0

    failed_cnt = session.execute(
        select(func.count(CertificateItem.id)).where(
            CertificateItem.job_id == job_id,
            CertificateItem.status == ItemStatus.FAILED,
        )
    ).scalar() or 0

    job.success_count = success_cnt
    job.failed_count = failed_cnt
    session.commit()


def finalize_job_status(session: Session, job_id: str) -> None:
    """Derive and persist final status when all items have finished."""
    job = session.execute(
        select(CertificateJob).where(CertificateJob.id == job_id)
    ).scalar_one_or_none()

    if not job:
        return

    # Verify if any item is still PENDING
    pending_cnt = session.execute(
        select(func.count(CertificateItem.id)).where(
            CertificateItem.job_id == job_id,
            CertificateItem.status == ItemStatus.PENDING,
        )
    ).scalar() or 0

    if pending_cnt > 0:
        return  # Job still in progress

    # Final counts
    total = job.total_count
    successes = job.success_count
    failures = job.failed_count

    if successes == total:
        job.status = JobStatus.COMPLETED
    elif successes > 0 and failures > 0:
        job.status = JobStatus.COMPLETED_WITH_ERRORS
    else:
        job.status = JobStatus.FAILED

    job.completed_at = datetime.now(timezone.utc)
    session.commit()
    logger.info(
        "Job %s finalized with status %s (success: %d, failed: %d, total: %d)",
        job.id,
        job.status.value,
        successes,
        failures,
        total,
    )


def process_job(job_id: str) -> None:
    """
    Main job processing routine.
    Fetches pending items and processes each in its own isolated transaction.
    """
    with get_db_session() as session:
        job = session.execute(
            select(CertificateJob).where(CertificateJob.id == job_id)
        ).scalar_one_or_none()

        if not job:
            logger.error("Job %s not found for processing", job_id)
            return

        # If job already completed, do nothing (idempotent)
        if job.status in [
            JobStatus.COMPLETED,
            JobStatus.COMPLETED_WITH_ERRORS,
        ]:
            logger.info("Job %s already finished with status %s", job_id, job.status)
            return

        # Mark job as PROCESSING
        if job.status == JobStatus.PENDING:
            job.status = JobStatus.PROCESSING
            if not job.started_at:
                job.started_at = datetime.now(timezone.utc)
            session.commit()

        # Capture static job metadata
        event_name = job.event_name
        issuer_name = job.issuer_name
        issue_date = job.issue_date

        # Retrieve all pending items in order
        pending_item_ids = session.execute(
            select(CertificateItem.id)
            .where(
                CertificateItem.job_id == job_id,
                CertificateItem.status == ItemStatus.PENDING,
            )
            .order_by(CertificateItem.index)
        ).scalars().all()

    # Process items sequentially (or per-thread) with per-item isolation
    for item_id in pending_item_ids:
        with get_db_session() as item_session:
            process_single_item(
                item_session,
                item_id=item_id,
                event_name=event_name,
                issuer_name=issuer_name,
                issue_date=issue_date,
            )
            # Update progress counters after each item so polling client sees live updates
            update_job_progress(item_session, job_id)

    # Finalize job status
    with get_db_session() as session:
        finalize_job_status(session, job_id)


def submit_job(job_id: str) -> None:
    """Submit a job for processing, either synchronously or to the thread pool."""
    if settings.SYNC_MODE:
        process_job(job_id)
    else:
        executor = get_executor()
        if executor:
            executor.submit(process_job, job_id)
        else:
            # Fallback if executor not started
            process_job(job_id)


def recover_incomplete_jobs() -> None:
    """
    Startup recovery: find any jobs left in PENDING or PROCESSING and resume them.
    Items already SUCCESS will be skipped, making recovery safe and idempotent.
    """
    with get_db_session() as session:
        incomplete_jobs = session.execute(
            select(CertificateJob.id).where(
                CertificateJob.status.in_([JobStatus.PENDING, JobStatus.PROCESSING])
            )
        ).scalars().all()

    if not incomplete_jobs:
        logger.info("Startup recovery: No incomplete jobs found.")
        return

    logger.info("Startup recovery: Resuming %d incomplete jobs...", len(incomplete_jobs))
    for j_id in incomplete_jobs:
        submit_job(j_id)
