from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import CertificateJob, ItemStatus
from app.services import processor


def test_individual_certificate_failure_isolation(
    client: TestClient, db_session: Session, monkeypatch
):
    """
    Monkeypatch renderer to raise for one specific recipient.
    Assert:
    - Other recipients succeed
    - Failing item is FAILED with useful error message
    - Job status is COMPLETED_WITH_ERRORS
    - Counts add up correctly
    """
    original_render = processor.render_certificate

    def mock_render(data, output_path):
        if data.recipient_name == "Crash User":
            raise RuntimeError("Simulated PDF font engine crash")
        return original_render(data, output_path)

    monkeypatch.setattr(processor, "render_certificate", mock_render)

    payload = {
        "event_name": "Resilient Generation Event",
        "recipients": [
            {"name": "Good User 1", "email": "good1@example.com"},
            {"name": "Crash User", "email": "crash@example.com"},
            {"name": "Good User 2", "email": "good2@example.com"},
        ],
    }

    response = client.post("/api/v1/certificate-jobs", json=payload)
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    # Check job status via API
    res = client.get(f"/api/v1/certificate-jobs/{job_id}")
    assert res.status_code == 200
    data = res.json()

    assert data["status"] == "COMPLETED_WITH_ERRORS"
    assert data["total_count"] == 3
    assert data["success_count"] == 2
    assert data["failed_count"] == 1

    # Check items via DB
    job = db_session.execute(
        select(CertificateJob).where(CertificateJob.id == job_id)
    ).scalar_one()

    items = sorted(job.items, key=lambda x: x.index)
    assert items[0].status == ItemStatus.SUCCESS
    assert items[0].recipient_name == "Good User 1"

    assert items[1].status == ItemStatus.FAILED
    assert items[1].recipient_name == "Crash User"
    assert "Simulated PDF font engine crash" in items[1].error_message

    assert items[2].status == ItemStatus.SUCCESS
    assert items[2].recipient_name == "Good User 2"
