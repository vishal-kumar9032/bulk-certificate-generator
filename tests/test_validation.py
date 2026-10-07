from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.models import CertificateJob, ItemStatus
from app.settings import settings


def test_missing_event_name_returns_422(client: TestClient):
    """Missing event_name must fail with 422."""
    payload = {
        "recipients": [{"name": "Asha", "email": "asha@example.com"}]
    }
    response = client.post("/api/v1/certificate-jobs", json=payload)
    assert response.status_code == 422


def test_blank_event_name_returns_422(client: TestClient):
    """Whitespace-only event_name must fail with 422."""
    payload = {
        "event_name": "    ",
        "recipients": [{"name": "Asha", "email": "asha@example.com"}],
    }
    response = client.post("/api/v1/certificate-jobs", json=payload)
    assert response.status_code == 422


def test_overlong_event_name_returns_422(client: TestClient):
    """Event name > 150 characters must fail with 422."""
    payload = {
        "event_name": "A" * 151,
        "recipients": [{"name": "Asha", "email": "asha@example.com"}],
    }
    response = client.post("/api/v1/certificate-jobs", json=payload)
    assert response.status_code == 422


def test_empty_recipients_list_returns_422(client: TestClient):
    """Empty recipients array must fail with 422."""
    payload = {
        "event_name": "FastAPI Workshop",
        "recipients": [],
    }
    response = client.post("/api/v1/certificate-jobs", json=payload)
    assert response.status_code == 422


def test_too_many_recipients_returns_422(client: TestClient, monkeypatch):
    """Exceeding MAX_RECIPIENTS_PER_JOB must fail with 422 mentioning the limit."""
    monkeypatch.setattr(settings, "MAX_RECIPIENTS_PER_JOB", 3)

    payload = {
        "event_name": "Scaled Event",
        "recipients": [
            {"name": f"User {i}", "email": f"user{i}@example.com"} for i in range(4)
        ],
    }
    response = client.post("/api/v1/certificate-jobs", json=payload)
    assert response.status_code == 422
    assert "exceeds maximum allowed limit of 3" in response.text


def test_invalid_issue_date_returns_422(client: TestClient):
    """Malformed date format must fail with 422."""
    payload = {
        "event_name": "FastAPI Workshop",
        "issue_date": "not-a-valid-date",
        "recipients": [{"name": "Asha", "email": "asha@example.com"}],
    }
    response = client.post("/api/v1/certificate-jobs", json=payload)
    assert response.status_code == 422


def test_lenient_recipient_validation(client: TestClient, db_session: Session):
    """
    Lenient recipient validation: invalid recipients become FAILED items with
    informative error messages, valid ones succeed, and emails are normalized to lowercase.
    """
    payload = {
        "event_name": "Robust Python 2026",
        "recipients": [
            {"name": "Valid First", "email": "First.User@Example.COM"},
            {"name": "", "email": "noname@example.com"},  # Missing name
            {"name": "Invalid Email", "email": "not-an-email"},  # Bad email
            {"name": "Duplicate Email", "email": "first.user@example.com"},  # Duplicate
            {"name": "A" * 105, "email": "toolong@example.com"},  # Overlong name
            {"name": "Valid Second", "email": "second@example.com"},  # Valid
        ],
    }

    response = client.post("/api/v1/certificate-jobs", json=payload)
    assert response.status_code == 202
    job_id = response.json()["job_id"]

    # Verify items in DB
    job = db_session.execute(
        select(CertificateJob).where(CertificateJob.id == job_id)
    ).scalar_one()

    items = sorted(job.items, key=lambda x: x.index)
    assert len(items) == 6

    # Item 0: Valid, email normalized
    assert items[0].status == ItemStatus.SUCCESS
    assert items[0].recipient_email == "first.user@example.com"
    assert items[0].error_message is None
    assert items[0].verification_code is not None

    # Item 1: Missing name
    assert items[1].status == ItemStatus.FAILED
    assert "name is required" in items[1].error_message

    # Item 2: Invalid email format
    assert items[2].status == ItemStatus.FAILED
    assert "invalid email format" in items[2].error_message

    # Item 3: Duplicate email
    assert items[3].status == ItemStatus.FAILED
    assert "duplicate email in this request (first seen at index 0)" in items[3].error_message

    # Item 4: Name exceeds 100 chars
    assert items[4].status == ItemStatus.FAILED
    assert "name exceeds 100 characters" in items[4].error_message

    # Item 5: Valid second
    assert items[5].status == ItemStatus.SUCCESS
    assert items[5].recipient_email == "second@example.com"

    # Overall job status
    assert job.success_count == 2
    assert job.failed_count == 4
    assert job.status.value == "COMPLETED_WITH_ERRORS"
