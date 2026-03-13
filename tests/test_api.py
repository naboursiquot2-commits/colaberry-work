from fastapi.testclient import TestClient

from src.api import app

client = TestClient(app)

VALID_KEY = {"x-api-key": "dev-secret-key"}


def test_match_endpoint_valid_request_returns_200():
    """
    A valid POST to /match with a correct API key and correctly-typed fields
    should return HTTP 200 and a paginated response containing ranked results.
    """
    response = client.post(
        "/match",
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
    assert isinstance(data["results"], list)


def test_match_endpoint_invalid_request_returns_422():
    """
    A POST to /match with skills as a string (not a list) should
    return HTTP 422 Unprocessable Entity — rejected by Pydantic validation.
    Auth passes first; Pydantic runs after.
    """
    response = client.post(
        "/match",
        headers=VALID_KEY,
        json={"skills": "python", "interests": ["mentorship"], "location": "NY"},
    )
    assert response.status_code == 422


def test_match_endpoint_logs_ranking_metrics(caplog):
    """
    /match must return 200 and emit one INFO log line containing
    profiles_loaded, ranked, and elapsed_ms metrics.
    """
    import logging

    with caplog.at_level(logging.INFO, logger="src.api"):
        response = client.post(
            "/match",
            headers=VALID_KEY,
            json={"skills": ["python"], "interests": ["mentorship"], "location": "NY"},
        )

    assert response.status_code == 200

    log_messages = [record.message for record in caplog.records]
    assert any("profiles_loaded" in msg for msg in log_messages)
    assert any("ranked" in msg for msg in log_messages)
    assert any("elapsed_ms" in msg for msg in log_messages)


def test_match_endpoint_missing_api_key_returns_401():
    """
    A POST to /match with no x-api-key header should return HTTP 401.
    """
    response = client.post(
        "/match",
        json={"skills": ["python"], "interests": ["mentorship"], "location": "NY"},
    )
    assert response.status_code == 401


def test_match_endpoint_wrong_api_key_returns_401():
    """
    A POST to /match with an incorrect x-api-key value should return HTTP 401.
    """
    response = client.post(
        "/match",
        headers={"x-api-key": "wrong-key"},
        json={"skills": ["python"], "interests": ["mentorship"], "location": "NY"},
    )
    assert response.status_code == 401


def test_match_endpoint_limit_parameter():
    """
    A POST to /match with limit=1 should return exactly one ranked result.
    """
    response = client.post(
        "/match",
        headers=VALID_KEY,
        json={
            "skills": ["python"],
            "interests": ["mentorship"],
            "location": "NY",
            "limit": 1,
        },
    )

    assert response.status_code == 200

    data = response.json()
    results = data["results"]

    assert isinstance(data, dict)
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert isinstance(results, list)
    assert len(results) == 1
    assert data["count"] == 1


def test_match_endpoint_offset_parameter():
    """
    A POST to /match with offset=1 should skip the first ranked result.
    """
    response = client.post(
        "/match",
        headers=VALID_KEY,
        json={
            "skills": ["python"],
            "interests": ["mentorship"],
            "location": "NY",
            "offset": 1,
        },
    )

    assert response.status_code == 200

    data = response.json()
    results = data["results"]

    assert isinstance(data, dict)
    assert data["offset"] == 1
    assert isinstance(results, list)
    assert len(results) > 0
    assert data["count"] == len(results)


def test_match_endpoint_limit_and_offset_combined():
    """
    A POST to /match with both limit and offset should return
    a correctly sliced subset of results.
    """
    response = client.post(
        "/match",
        headers=VALID_KEY,
        json={
            "skills": ["python"],
            "interests": ["mentorship"],
            "location": "NY",
            "limit": 2,
            "offset": 1,
        },
    )

    assert response.status_code == 200

    data = response.json()
    results = data["results"]

    assert isinstance(data, dict)
    assert data["limit"] == 2
    assert data["offset"] == 1
    assert isinstance(results, list)
    assert len(results) <= 2
    assert data["count"] == len(results)


def test_match_endpoint_limit_zero_returns_422():
    """
    A POST to /match with limit=0 should return HTTP 422 —
    rejected by Pydantic validation (ge=1 constraint).
    """
    response = client.post(
        "/match",
        headers=VALID_KEY,
        json={"skills": ["python"], "interests": ["mentorship"], "location": "NY", "limit": 0},
    )
    assert response.status_code == 422


def test_match_endpoint_negative_offset_returns_422():
    """
    A POST to /match with offset=-1 should return HTTP 422 —
    rejected by Pydantic validation (ge=0 constraint).
    """
    response = client.post(
        "/match",
        headers=VALID_KEY,
        json={"skills": ["python"], "interests": ["mentorship"], "location": "NY", "offset": -1},
    )
    assert response.status_code == 422