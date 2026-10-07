import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from starlette.background import BackgroundTask

from app.database import get_db
from app.models import ItemStatus, JobStatus
from app.schemas import (
    CertificateJobCreateRequest,
    CertificateJobCreateResponse,
    CertificateJobDetailResponse,
    CertificateItemResponse,
    PaginatedCertificatesResponse,
    VerificationLookupResponse,
)
from app.services import job_service, processor, zip_builder
from app.settings import settings

router = APIRouter(prefix="/api/v1", tags=["Certificates"])


def build_item_response(job_id: str, item) -> CertificateItemResponse:
    """Build response model for a single certificate item."""
    download_url = None
    if item.status == ItemStatus.SUCCESS:
        download_url = f"/api/v1/certificate-jobs/{job_id}/certificates/{item.id}/download"

    return CertificateItemResponse(
        id=item.id,
        index=item.index,
        recipient_name=item.recipient_name,
        recipient_email=item.recipient_email,
        status=item.status,
        error_message=item.error_message,
        verification_code=item.verification_code,
        download_url=download_url,
    )


@router.post(
    "/certificate-jobs",
    response_model=CertificateJobCreateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Create a bulk certificate generation job",
)
def create_job(
    request: CertificateJobCreateRequest,
    db: Session = Depends(get_db),
):
    """
    Accepts a bulk certificate generation request.
    Creates job and items with lenient recipient validation, then kicks off processing.
    Returns 202 Accepted immediately with status URL.
    """
    job = job_service.create_certificate_job(db, request)

    # If there are pending items, dispatch to background processor
    if job.status == JobStatus.PENDING:
        processor.submit_job(job.id)

    # Refresh job in case SYNC_MODE finished it
    db.refresh(job)

    return CertificateJobCreateResponse(
        job_id=job.id,
        status=job.status,
        total_count=job.total_count,
        status_url=f"/api/v1/certificate-jobs/{job.id}",
    )


@router.get(
    "/certificate-jobs/{job_id}",
    response_model=CertificateJobDetailResponse,
    summary="Get job status and progress",
)
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
):
    """Retrieve high-level progress and counters for a certificate job."""
    job = job_service.get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certificate job '{job_id}' not found",
        )

    pending_count = max(0, job.total_count - (job.success_count + job.failed_count))
    progress_percent = (
        round(((job.success_count + job.failed_count) / job.total_count) * 100)
        if job.total_count > 0
        else 0
    )

    download_all_url = None
    if job.success_count > 0:
        download_all_url = f"/api/v1/certificate-jobs/{job.id}/download"

    return CertificateJobDetailResponse(
        id=job.id,
        event_name=job.event_name,
        issuer_name=job.issuer_name,
        issue_date=job.issue_date,
        status=job.status,
        total_count=job.total_count,
        success_count=job.success_count,
        failed_count=job.failed_count,
        pending_count=pending_count,
        progress_percent=progress_percent,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        download_all_url=download_all_url,
    )


@router.get(
    "/certificate-jobs/{job_id}/certificates",
    response_model=PaginatedCertificatesResponse,
    summary="List certificate items for a job",
)
def list_certificates(
    job_id: str,
    limit: int = Query(default=50, ge=1, le=200, description="Items per page"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    status: Optional[ItemStatus] = Query(default=None, description="Filter by item status"),
    db: Session = Depends(get_db),
):
    """Paginated list of certificate items showing recipient status and failure reasons."""
    job = job_service.get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certificate job '{job_id}' not found",
        )

    total, items = job_service.get_job_items(
        db,
        job_id=job_id,
        limit=limit,
        offset=offset,
        status_filter=status,
    )

    item_responses = [build_item_response(job_id, it) for it in items]

    return PaginatedCertificatesResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=item_responses,
    )


@router.get(
    "/certificate-jobs/{job_id}/certificates/{certificate_id}/download",
    summary="Download a single certificate PDF",
)
def download_single_certificate(
    job_id: str,
    certificate_id: str,
    db: Session = Depends(get_db),
):
    """Download an individual generated certificate PDF."""
    item = job_service.get_item_by_id(db, job_id=job_id, item_id=certificate_id)
    if not item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certificate '{certificate_id}' not found in job '{job_id}'",
        )

    if item.status != ItemStatus.SUCCESS or not item.file_path:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Certificate cannot be downloaded: current status is '{item.status.value}'"
            + (f" ({item.error_message})" if item.error_message else ""),
        )

    abs_path = settings.STORAGE_DIR / item.file_path
    if not abs_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Certificate file is missing from storage",
        )

    safe_name = zip_builder.sanitize_filename(item.recipient_name or "certificate")
    filename = f"certificate_{safe_name}.pdf"

    return FileResponse(
        path=abs_path,
        media_type="application/pdf",
        filename=filename,
    )


@router.get(
    "/certificate-jobs/{job_id}/download",
    summary="Download ZIP archive of all certificates in job",
)
def download_job_zip(
    job_id: str,
    db: Session = Depends(get_db),
):
    """Download a ZIP archive containing all successfully generated certificates."""
    job = job_service.get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certificate job '{job_id}' not found",
        )

    try:
        zip_path = zip_builder.create_job_zip(db, job_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        )

    safe_event_name = zip_builder.sanitize_filename(job.event_name)
    download_filename = f"{safe_event_name}_certificates.zip"

    # Clean up the temporary zip file after the response is sent
    return FileResponse(
        path=zip_path,
        media_type="application/zip",
        filename=download_filename,
        background=BackgroundTask(os.remove, zip_path),
    )


# ------------------ Optional Extras ------------------


@router.get(
    "/certificates/verify/{verification_code}",
    response_model=VerificationLookupResponse,
    summary="Verify authenticity of a certificate by verification code",
)
def verify_certificate(
    verification_code: str,
    db: Session = Depends(get_db),
):
    """Lookup and verify certificate details by its unique verification code."""
    item = job_service.get_item_by_verification_code(db, verification_code.strip())
    if not item or not item.job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No valid certificate found for verification code '{verification_code}'",
        )

    return VerificationLookupResponse(
        verification_code=item.verification_code,
        recipient_name=item.recipient_name,
        event_name=item.job.event_name,
        issuer_name=item.job.issuer_name,
        issue_date=item.job.issue_date,
        issued_at=item.completed_at or item.created_at,
    )


@router.post(
    "/certificate-jobs/{job_id}/retry-failed",
    response_model=CertificateJobDetailResponse,
    summary="Retry items that failed during generation",
)
def retry_failed_items(
    job_id: str,
    db: Session = Depends(get_db),
):
    """
    Re-processes items that failed specifically at generation time
    (excludes permanent validation failures).
    """
    job = job_service.get_job_by_id(db, job_id)
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Certificate job '{job_id}' not found",
        )

    # Only retry items where error_message starts with 'Generation error'
    for it in job.items:
        if it.status == ItemStatus.FAILED and it.error_message and it.error_message.startswith("Generation error"):
            it.status = ItemStatus.PENDING
            it.error_message = None
            it.completed_at = None

    db.commit()
    processor.submit_job(job_id)
    db.refresh(job)

    return get_job(job_id=job_id, db=db)
