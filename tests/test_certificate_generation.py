from datetime import date
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import CertificateJob, ItemStatus
from app.services.certificate_renderer import render_certificate, CertificateData
from app.settings import settings


def test_renderer_unit_long_name_and_event(tmp_path: Path):
    """
    Unit test for renderer: ensures extremely long names and event titles
    fit without raising exceptions and produce valid PDF output.
    """
    pdf_out = tmp_path / "long_certificate.pdf"
    data = CertificateData(
        recipient_name="Hubert Blaine Wolfeschlegelsteinhausenbergerdorff Senior The Third",
        event_name="Annual Global Conference on Advanced Asynchronous Distributed Cloud Native Architectures 2026",
        issue_date=date(2026, 12, 31),
        issuer_name="International Institute of Advanced Computational Technologies",
        verification_code="TEST-CODE",
    )

    render_certificate(data, pdf_out)

    assert pdf_out.exists()
    content = pdf_out.read_bytes()
    assert content.startswith(b"%PDF")
    assert len(content) > 1000  # Non-trivial size


def test_certificate_generation_file_on_disk(client: TestClient, db_session: Session):
    """
    Generates certificate via API, verifies PDF file exists on disk,
    begins with %PDF header, has non-trivial size, and has verification code.
    """
    payload = {
        "event_name": "Full Stack Mastery",
        "issuer_name": "Tech Corp",
        "recipients": [
            {"name": "Ananya Sharma", "email": "ananya@example.com"}
        ],
    }

    response = client.post("/api/v1/certificate-jobs", json=payload)
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    job = db_session.execute(
        select(CertificateJob).where(CertificateJob.id == job_id)
    ).scalar_one()

    item = job.items[0]
    assert item.status == ItemStatus.SUCCESS
    assert item.verification_code is not None
    assert len(item.verification_code) == 9  # ABCD-EFGH
    assert item.file_path is not None

    file_path = settings.STORAGE_DIR / item.file_path
    assert file_path.exists()
    data = file_path.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 5000  # Substantial certificate file size
