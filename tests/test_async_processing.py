import time
from fastapi.testclient import TestClient
from app.settings import settings


def test_async_background_processing(client: TestClient, monkeypatch):
    """
    Test end-to-end asynchronous processing in ThreadPoolExecutor
    when SYNC_MODE is false.
    """
    monkeypatch.setattr(settings, "SYNC_MODE", False)

    payload = {
        "event_name": "Async Concurrency Masterclass",
        "issuer_name": "Antigravity Lab",
        "recipients": [
            {"name": "Async User 1", "email": "async1@example.com"},
            {"name": "Async User 2", "email": "async2@example.com"},
        ],
    }

    res = client.post("/api/v1/certificate-jobs", json=payload)
    assert res.status_code == 202
    job_id = res.json()["job_id"]

    # Poll status until complete or timeout
    max_wait_seconds = 5.0
    start_time = time.time()
    final_status = None

    while time.time() - start_time < max_wait_seconds:
        status_res = client.get(f"/api/v1/certificate-jobs/{job_id}")
        assert status_res.status_code == 200
        data = status_res.json()
        if data["status"] in ["COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"]:
            final_status = data["status"]
            break
        time.sleep(0.05)

    assert final_status == "COMPLETED"
    assert data["success_count"] == 2
    assert data["progress_percent"] == 100
