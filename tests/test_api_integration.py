from fastapi.testclient import TestClient
from src.api import app

client = TestClient(app)

VALID_KEY = {"x-api-key": "dev-secret-key"}


def test_health_endpoint_returns_ok():
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_match_requires_api_key():
    response = client.post(
        "/match",
        json={"skills": ["python"], "interests": ["mentorship"], "location": "NY"},
    )

    assert response.status_code == 401


def test_match_with_valid_api_key_returns_ranked_results():
    response = client.post(
        "/match",
        headers=VALID_KEY,
        json={"skills": ["python"], "interests": ["mentorship"], "location": "NY"},
    )

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)
    assert len(data) > 0
    assert "alumni_id" in data[0]
    assert "total_score" in data[0]