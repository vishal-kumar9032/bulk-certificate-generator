import os
from datetime import date
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import CertificateJob, CertificateItem, JobStatus, ItemStatus
from app.services import processor, job_service
from app.schemas import CertificateJobCreateRequest
from app.settings import settings


def test_idempotent_reprocessing(client: TestClient, db_session: Session):
    """Re-running process_job on an already completed job does not duplicate files."""
    payload = {
        "event_name": "Idempotency Workshop",
        "recipients": [{"name": "Asha Verma", "email": "asha@example.com"}],
    }

    res = client.post("/api/v1/certificate-jobs", json=payload)
    job_id = res.json()["job_id"]

    job = db_session.execute(
        select(CertificateJob).where(CertificateJob.id == job_id)
    ).scalar_one()

    assert job.status == JobStatus.COMPLETED
    file_path = settings.STORAGE_DIR / job.items[0].file_path
    mtime_before = os.path.getmtime(file_path)

    # Re-run processor directly on finished job
    processor.process_job(job_id)

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    mtime_after = os.path.getmtime(file_path)
    # File was not re-written because item was already SUCCESS
    assert mtime_before == mtime_after


def test_startup_recovery(client: TestClient, db_session: Session):
    """
    A job left in PROCESSING with pending items (e.g., following a server restart)
    is properly picked up and completed by recover_incomplete_jobs().
    """
    request_data = CertificateJobCreateRequest(
        event_name="Recovery Crash Test",
        recipients=[
            {"name": "Done User", "email": "done@example.com"},
            {"name": "Unfinished User", "email": "unfinished@example.com"},
        ],
    )
    job = job_service.create_certificate_job(db_session, request_data)

    # Manually simulate partial processing: first item SUCCESS, second PENDING, job in PROCESSING
    items = sorted(job.items, key=lambda x: x.index)
    first_item = items[0]
    first_item.status = ItemStatus.SUCCESS
    first_item.file_path = f"{job.id}/{first_item.id}.pdf"
    first_abs_path = settings.STORAGE_DIR / first_item.file_path
    first_abs_path.parent.mkdir(parents=True, exist_ok=True)
    first_abs_path.write_bytes(b"%PDF-1.4 test content")

    job.status = JobStatus.PROCESSING
    job.success_count = 1
    db_session.commit()

    # Invoke startup recovery routine
    processor.recover_incomplete_jobs()

    db_session.refresh(job)
    assert job.status == JobStatus.COMPLETED
    assert job.success_count == 2
    assert job.failed_count == 0

    # Ensure second item now has generated PDF
    second_item = items[1]
    db_session.refresh(second_item)
    assert second_item.status == ItemStatus.SUCCESS
    assert (settings.STORAGE_DIR / second_item.file_path).exists()


def test_verification_endpoint(client: TestClient):
    """Test certificate verification by verification code."""
    payload = {
        "event_name": "Verified Graduate",
        "issuer_name": "Oxford Online",
        "recipients": [{"name": "Priya Sharma", "email": "priya@example.com"}],
    }

    res = client.post("/api/v1/certificate-jobs", json=payload)
    job_id = res.json()["job_id"]

    # Get items to find verification code
    items_res = client.get(f"/api/v1/certificate-jobs/{job_id}/certificates")
    v_code = items_res.json()["items"][0]["verification_code"]
    assert v_code is not None

    # Call verification endpoint
    verify_res = client.get(f"/api/v1/certificates/verify/{v_code}")
    assert verify_res.status_code == 200
    v_data = verify_res.json()
    assert v_data["verification_code"] == v_code
    assert v_data["recipient_name"] == "Priya Sharma"
    assert v_data["event_name"] == "Verified Graduate"
    assert v_data["issuer_name"] == "Oxford Online"


def test_retry_failed_generation(client: TestClient, db_session: Session, monkeypatch):
    """Test retrying items that failed during generation."""
    # First attempt: monkeypatch renderer to fail
    call_count = 0

    def flaky_render(data, output_path):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("Transient network/disk failure")
        return processor.render_certificate(data, output_path)

    monkeypatch.setattr(processor, "render_certificate", flaky_render)

    payload = {
        "event_name": "Retryable Event",
        "recipients": [{"name": "Retry Candidate", "email": "retry@example.com"}],
    }

    res = client.post("/api/v1/certificate-jobs", json=payload)
    job_id = res.json()["job_id"]

    # Check status: should be FAILED due to generation error
    status_res = client.get(f"/api/v1/certificate-jobs/{job_id}")
    assert status_res.json()["status"] == "FAILED"
    assert status_res.json()["failed_count"] == 1

    # Remove flaky mock
    monkeypatch.undo()

    # Call retry endpoint
    retry_res = client.post(f"/api/v1/certificate-jobs/{job_id}/retry-failed")
    assert retry_res.status_code == 200

    # Job should now be COMPLETED
    check_res = client.get(f"/api/v1/certificate-jobs/{job_id}")
    assert check_res.json()["status"] == "COMPLETED"
    assert check_res.json()["success_count"] == 1
    assert check_res.json()["failed_count"] == 0
