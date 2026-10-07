from fastapi.testclient import TestClient
from sqlalchemy.orm import Session
from app.models import JobStatus
from app.schemas import CertificateJobCreateRequest
from app.services import job_service


def test_job_not_found_returns_404(client: TestClient):
    """Querying an unknown job ID must return 404."""
    response = client.get("/api/v1/certificate-jobs/non-existent-uuid")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


def test_intermediate_state_pending(client: TestClient, db_session: Session):
    """
    Test creating a job without running processor:
    Job is PENDING, with 0% progress and pending_count equal to total_count.
    """
    request_data = CertificateJobCreateRequest(
        event_name="Pending Test Event",
        recipients=[
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
        ],
    )
    # Call service directly to create job without submitting to processor
    job = job_service.create_certificate_job(db_session, request_data)

    response = client.get(f"/api/v1/certificate-jobs/{job.id}")
    assert response.status_code == 200
    data = response.json()

    assert data["status"] == "PENDING"
    assert data["total_count"] == 2
    assert data["success_count"] == 0
    assert data["failed_count"] == 0
    assert data["pending_count"] == 2
    assert data["progress_percent"] == 0
    assert data["download_all_url"] is None


def test_final_status_completed(client: TestClient):
    """All items valid and generated -> COMPLETED."""
    payload = {
        "event_name": "Full Success Workshop",
        "recipients": [
            {"name": "Alice", "email": "alice@example.com"},
            {"name": "Bob", "email": "bob@example.com"},
        ],
    }
    response = client.post("/api/v1/certificate-jobs", json=payload)
    job_id = response.json()["job_id"]

    res = client.get(f"/api/v1/certificate-jobs/{job_id}")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "COMPLETED"
    assert data["total_count"] == 2
    assert data["success_count"] == 2
    assert data["failed_count"] == 0
    assert data["pending_count"] == 0
    assert data["progress_percent"] == 100
    assert data["download_all_url"] is not None


def test_final_status_completed_with_errors(client: TestClient):
    """Mix of valid and invalid items -> COMPLETED_WITH_ERRORS."""
    payload = {
        "event_name": "Mixed Workshop",
        "recipients": [
            {"name": "Valid User", "email": "valid@example.com"},
            {"name": "", "email": "missingname@example.com"},
        ],
    }
    response = client.post("/api/v1/certificate-jobs", json=payload)
    job_id = response.json()["job_id"]

    res = client.get(f"/api/v1/certificate-jobs/{job_id}")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "COMPLETED_WITH_ERRORS"
    assert data["total_count"] == 2
    assert data["success_count"] == 1
    assert data["failed_count"] == 1
    assert data["progress_percent"] == 100
    assert data["download_all_url"] is not None


def test_final_status_failed_all_invalid(client: TestClient):
    """All items invalid -> job status FAILED."""
    payload = {
        "event_name": "All Invalid Workshop",
        "recipients": [
            {"name": "", "email": "bad1@example.com"},
            {"name": "Bad Email", "email": "not-an-email"},
        ],
    }
    response = client.post("/api/v1/certificate-jobs", json=payload)
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    res = client.get(f"/api/v1/certificate-jobs/{job_id}")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "FAILED"
    assert data["total_count"] == 2
    assert data["success_count"] == 0
    assert data["failed_count"] == 2
    assert data["progress_percent"] == 100
    assert data["download_all_url"] is None
