"""Integration tests for LabData Analytics v0.3 using synthetic sample data."""
import io


def new_sample(sample_id="TEST-001"):
    return {
        "sample_id": sample_id,
        "sample_type": "Blood",
        "collected_at": "2026-11-19",
        "status": "received",
        "result_value": None,
    }


def upload_csv(client, content):
    return client.post(
        "/samples/import-csv",
        files={"file": ("samples.csv", io.BytesIO(content.encode("utf-8")), "text/csv")},
    )


def test_initial_seed_and_summary(client):
    response = client.get("/samples")
    assert response.status_code == 200
    assert response.json()["count"] == 5
    summary = client.get("/summary")
    assert summary.status_code == 200
    assert summary.json() == {
        "total_samples": 5,
        "by_status": {"completed": 2, "processing": 2, "received": 1},
    }


def test_create_and_get_sample(client):
    response = client.post("/samples", json=new_sample())
    assert response.status_code == 201
    assert response.json()["sample_id"] == "TEST-001"
    result = client.get("/samples/TEST-001")
    assert result.status_code == 200
    assert result.json()["status"] == "received"
    assert client.get("/samples").json()["count"] == 6


def test_duplicate_sample_is_rejected(client):
    assert client.post("/samples", json=new_sample()).status_code == 201
    duplicate = client.post("/samples", json=new_sample())
    assert duplicate.status_code == 409
    assert client.get("/samples").json()["count"] == 6


def test_update_sample_and_status_filter(client):
    assert client.post("/samples", json=new_sample()).status_code == 201
    updated = client.patch(
        "/samples/TEST-001", json={"status": "completed", "result_value": 5.8}
    )
    assert updated.status_code == 200
    assert updated.json()["result_value"] == 5.8
    assert updated.json()["status"] == "completed"
    result = client.get("/samples", params={"status": "completed"})
    assert result.status_code == 200
    assert result.json()["count"] == 3


def test_valid_csv_import(client):
    content = (
        "sample_id,sample_type,collected_at,status,result_value\n"
        "TEST-007,Blood,2026-11-19,received,\n"
        "TEST-008,Urine,2026-11-20,completed,6.1\n"
    )
    result = upload_csv(client, content)
    assert result.status_code == 200
    assert result.json() == {"imported": 2, "sample_ids": ["TEST-007", "TEST-008"]}
    assert client.get("/summary").json()["total_samples"] == 7


def test_csv_duplicate_import_fails_atomically(client):
    content = (
        "sample_id,sample_type,collected_at,status,result_value\n"
        "TEST-007,Blood,2026-11-19,received,\n"
        "TEST-008,Urine,2026-11-20,completed,6.1\n"
    )
    assert upload_csv(client, content).status_code == 200
    retry = upload_csv(client, content)
    assert retry.status_code == 409
    assert sorted(retry.json()["detail"]["ids"]) == ["TEST-007", "TEST-008"]
    assert client.get("/samples").json()["count"] == 7


def test_invalid_csv_does_not_partially_import(client):
    content = (
        "sample_id,sample_type,collected_at,status,result_value\n"
        "TEST-009,Blood,2026-11-19,received,\n"
        "TEST-010,Blood,not-a-date,completed,5.0\n"
    )
    result = upload_csv(client, content)
    assert result.status_code == 422
    assert "Validation failed" in result.json()["detail"]["message"]
    assert client.get("/samples/TEST-009").status_code == 404
    assert client.get("/samples").json()["count"] == 5


def test_missing_sample_returns_404(client):
    assert client.get("/samples/NOT-THERE").status_code == 404
    assert client.patch("/samples/NOT-THERE", json={"status": "completed"}).status_code == 404
