from fastapi.testclient import TestClient
from src.api import app

client = TestClient(app)

VALID_KEY = {"x-api-key": "dev-secret-key"}


def test_health_endpoint_returns_ok():
    response = client.get("/v1/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_match_requires_api_key():
    response = client.post(
        "/v1/match",
        json={"skills": ["python"], "interests": ["mentorship"], "location": "NY"},
    )

    assert response.status_code == 401


def test_match_with_valid_api_key_returns_ranked_results():
    response = client.post(
        "/v1/match",
        headers=VALID_KEY,
        json={"skills": ["python"], "interests": ["mentorship"], "location": "NY"},
    )

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, dict)
    assert "count" in data
    assert "limit" in data
    assert "offset" in data
    assert "results" in data

    results = data["results"]

    assert isinstance(results, list)
    assert len(results) > 0
    assert "alumni_id" in results[0]
    assert "total_score" in results[0]


def test_alumni_endpoint_requires_api_key():
    response = client.get("/v1/alumni")

    assert response.status_code == 401


def test_alumni_endpoint_with_valid_api_key_returns_paginated_results():
    response = client.get("/v1/alumni", headers=VALID_KEY)

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, dict)
    assert "count" in data
    assert "limit" in data
    assert "offset" in data
    assert "results" in data
    assert isinstance(data["results"], list)