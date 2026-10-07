from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import CertificateJob, CertificateItem, JobStatus


def test_health_check(client: TestClient):
    """Test health check returns status ok."""
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_create_job_valid_payload(client: TestClient, db_session: Session):
    """
    Valid payload returns 202 Accepted with job_id, status_url,
    and correctly creates the job and recipient items in the DB.
    """
    payload = {
        "event_name": "Python Advanced Workshop 2026",
        "issuer_name": "Code Academy",
        "issue_date": "2026-10-01",
        "recipients": [
            {"name": "Asha Verma", "email": "asha@example.com"},
            {"name": "Rohan Das", "email": "rohan@example.com"},
        ],
    }

    response = client.post("/api/v1/certificate-jobs", json=payload)
    assert response.status_code == 202
    data = response.json()

    assert "job_id" in data
    job_id = data["job_id"]
    assert data["total_count"] == 2
    assert data["status_url"] == f"/api/v1/certificate-jobs/{job_id}"

    # Verify database state
    job = db_session.execute(
        select(CertificateJob).where(CertificateJob.id == job_id)
    ).scalar_one_or_none()

    assert job is not None
    assert job.event_name == "Python Advanced Workshop 2026"
    assert job.issuer_name == "Code Academy"
    assert job.total_count == 2
    assert len(job.items) == 2

    # Check recipient items
    items = sorted(job.items, key=lambda x: x.index)
    assert items[0].index == 0
    assert items[0].recipient_name == "Asha Verma"
    assert items[0].recipient_email == "asha@example.com"
    assert items[1].index == 1
    assert items[1].recipient_name == "Rohan Das"
    assert items[1].recipient_email == "rohan@example.com"
