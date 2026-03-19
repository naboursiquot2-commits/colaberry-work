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


def test_response_includes_x_request_id_header():
    response = client.get("/v1/health")

    assert response.status_code == 200
    assert "x-request-id" in response.headers
    assert len(response.headers["x-request-id"]) > 0


def test_get_alumni_by_id_returns_profile():
    response = client.get("/v1/alumni/A001", headers=VALID_KEY)

    assert response.status_code == 200
    assert response.json()["alumni_id"] == "A001"


def test_get_alumni_by_id_not_found_returns_404():
    response = client.get("/v1/alumni/DOES_NOT_EXIST", headers=VALID_KEY)

    assert response.status_code == 404
    assert response.json()["detail"] == "Alumni not found"


def test_client_supplied_x_request_id_is_echoed_in_response():
    response = client.get(
        "/v1/health",
        headers={"X-Request-ID": "test-request-123"},
    )

    assert response.status_code == 200
    assert response.headers["x-request-id"] == "test-request-123"