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
    assert isinstance(data["results"], list)


def test_match_endpoint_invalid_request_returns_422():
    """
    A POST to /match with skills as a string (not a list) should
    return HTTP 422 Unprocessable Entity — rejected by Pydantic validation.
    Auth passes first; Pydantic runs after.
    """
    response = client.post(
        "/v1/match",
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
            "/v1/match",
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
        "/v1/match",
        json={"skills": ["python"], "interests": ["mentorship"], "location": "NY"},
    )
    assert response.status_code == 401


def test_match_endpoint_wrong_api_key_returns_401():
    """
    A POST to /match with an incorrect x-api-key value should return HTTP 401.
    """
    response = client.post(
        "/v1/match",
        headers={"x-api-key": "wrong-key"},
        json={"skills": ["python"], "interests": ["mentorship"], "location": "NY"},
    )
    assert response.status_code == 401


def test_match_endpoint_limit_parameter():
    """
    A POST to /match with limit=1 should return exactly one ranked result.
    """
    response = client.post(
        "/v1/match",
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
        "/v1/match",
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
        "/v1/match",
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
        "/v1/match",
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
        "/v1/match",
        headers=VALID_KEY,
        json={"skills": ["python"], "interests": ["mentorship"], "location": "NY", "offset": -1},
    )
    assert response.status_code == 422


def test_match_endpoint_results_include_matched_on():
    """
    Each result in /match response must include a matched_on field.
    """
    response = client.post(
        "/v1/match",
        headers=VALID_KEY,
        json={"skills": ["python"], "interests": ["mentorship"], "location": "NY"},
    )

    assert response.status_code == 200

    results = response.json()["results"]
    assert len(results) > 0
    for result in results:
        assert "matched_on" in result


def test_rate_limit_middleware_returns_429_after_max_requests(monkeypatch):
    """
    With RATE_LIMIT_MAX=2, the third request from the same API key within
    the rate limit window must be rejected with HTTP 429 and the detail
    "Rate limit exceeded".
    """
    import src.api as api_module

    monkeypatch.setattr(api_module, "_RATE_LIMIT_MAX", 2)
    monkeypatch.setattr(api_module, "_RATE_LIMIT_WINDOW", 60)
    api_module._rate_limit_counts.clear()

    r1 = client.get("/v1/health")
    r2 = client.get("/v1/health")
    r3 = client.get("/v1/health")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 429
    error = r3.json()["error"]
    assert error["code"] == 429
    assert error["message"] == "Rate limit exceeded"
    assert error["request_id"] == "-"


def test_health_endpoint_returns_profiles_loaded_count():
    """
    GET /v1/health must return 200 with status "ok" and a profiles_loaded
    count of zero or more when profiles are available.
    """
    with TestClient(app) as local_client:
        response = local_client.get("/v1/health")

    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "ok"
    assert "profiles_loaded" in data
    assert data["profiles_loaded"] >= 0


def test_health_endpoint_returns_503_when_profiles_not_loaded():
    """
    GET /v1/health must return 503 with status "error" when app.state.profiles
    is None (profiles failed to load at startup).
    """
    import src.api as api_module

    with TestClient(app) as local_client:
        original = api_module.app.state.profiles
        api_module.app.state.profiles = None
        try:
            response = local_client.get("/v1/health")
        finally:
            api_module.app.state.profiles = original

    assert response.status_code == 503

    data = response.json()
    assert data["status"] == "error"
    assert data["detail"] == "profiles not loaded"


def test_middleware_logs_access_line_for_every_request(caplog):
    """
    Every request must emit one INFO access log line from the middleware
    containing method, path, and status_code.
    """
    import logging

    with caplog.at_level(logging.INFO, logger="src.api"):
        response = client.get("/v1/health")

    assert response.status_code == 200

    log_messages = [record.message for record in caplog.records]
    assert any(
        "method=GET" in msg and "path=/v1/health" in msg and "status_code=200" in msg
        for msg in log_messages
    )


def test_match_endpoint_whitespace_only_skill_returns_422():
    """
    A POST to /match with a whitespace-only skill item must return 422
    using the structured error envelope.
    """
    response = client.post(
        "/v1/match",
        headers=VALID_KEY,
        json={"skills": ["   "], "interests": [], "location": "NY"},
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == 422
    assert error["message"] == "Validation error"


def test_match_endpoint_skills_exceeding_max_length_returns_422():
    """
    A POST to /match with more than 50 skills must return 422
    using the structured error envelope.
    """
    response = client.post(
        "/v1/match",
        headers=VALID_KEY,
        json={"skills": [f"skill{i}" for i in range(51)], "interests": [], "location": "NY"},
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == 422
    assert error["message"] == "Validation error"