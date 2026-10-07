import io
import zipfile
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import CertificateJob, ItemStatus


def test_retrieval_and_downloads(client: TestClient, db_session: Session):
    """
    Test single PDF download, failed item download 409, wrong job/cert 404,
    ZIP archive download, pagination, and status filters.
    """
    payload = {
        "event_name": "Retrieval Mastery",
        "recipients": [
            {"name": "Valid User One", "email": "valid1@example.com"},
            {"name": "Valid User Two", "email": "valid2@example.com"},
            {"name": "", "email": "failed@example.com"},  # Will fail
        ],
    }

    create_res = client.post("/api/v1/certificate-jobs", json=payload)
    assert create_res.status_code == 202
    job_id = create_res.json()["job_id"]

    # 1. Listing endpoint with pagination and status filter
    list_res = client.get(f"/api/v1/certificate-jobs/{job_id}/certificates?limit=10&offset=0")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert list_data["total"] == 3
    assert len(list_data["items"]) == 3

    # Check status filter for SUCCESS
    succ_res = client.get(f"/api/v1/certificate-jobs/{job_id}/certificates?status=SUCCESS")
    assert succ_res.status_code == 200
    assert succ_res.json()["total"] == 2

    # Check status filter for FAILED
    fail_res = client.get(f"/api/v1/certificate-jobs/{job_id}/certificates?status=FAILED")
    assert fail_res.status_code == 200
    assert fail_res.json()["total"] == 1
    failed_item_id = fail_res.json()["items"][0]["id"]
    successful_item_id = succ_res.json()["items"][0]["id"]

    # 2. Single PDF download for successful item
    pdf_res = client.get(
        f"/api/v1/certificate-jobs/{job_id}/certificates/{successful_item_id}/download"
    )
    assert pdf_res.status_code == 200
    assert pdf_res.headers["content-type"] == "application/pdf"
    assert "attachment; filename=" in pdf_res.headers["content-disposition"]
    assert pdf_res.content.startswith(b"%PDF")

    # 3. Download of a failed item -> 409 Conflict
    fail_dl_res = client.get(
        f"/api/v1/certificate-jobs/{job_id}/certificates/{failed_item_id}/download"
    )
    assert fail_dl_res.status_code == 409
    assert "cannot be downloaded" in fail_dl_res.json()["detail"].lower()

    # 4. Wrong job / certificate combination -> 404 Not Found
    wrong_res = client.get(
        f"/api/v1/certificate-jobs/wrong-job-id/certificates/{successful_item_id}/download"
    )
    assert wrong_res.status_code == 404

    # 5. ZIP download of all successful certificates
    zip_res = client.get(f"/api/v1/certificate-jobs/{job_id}/download")
    assert zip_res.status_code == 200
    assert zip_res.headers["content-type"] == "application/zip"

    # Inspect zip contents
    with zipfile.ZipFile(io.BytesIO(zip_res.content)) as zf:
        file_list = zf.namelist()
        assert len(file_list) == 2
        # Files should be numbered and named safely
        assert any("valid-user-one" in f for f in file_list)
        assert any("valid-user-two" in f for f in file_list)
