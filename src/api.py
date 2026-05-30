import logging
import os
import time
import uuid
from collections import defaultdict
from contextlib import asynccontextmanager
from contextvars import ContextVar

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator

from pythonjsonlogger import json as jsonlogger

from src.api_key_repository import ApiKeyRepository
from src.matching_engine import load_alumni_profiles_csv, rank_alumni
from src.repository import (
    AlumniAlreadyExistsError,
    AlumniNotFoundError,
    CsvAlumniRepository,
    SqliteAlumniRepository,
)
from fastapi.responses import Response

_API_KEY = os.getenv("API_KEY")
if not _API_KEY:
    raise ValueError("API_KEY environment variable is required and must not be empty")
DATA_PATH = os.getenv("DATA_PATH", "data/sample_alumni.csv")
DATABASE_PATH = os.getenv("DATABASE_PATH")  # optional; if set and file exists, DB loader is used
_SERVICE_VERSION = os.getenv("SERVICE_VERSION", "0.1.0")
_SERVICE_NAME = "Colaberry Nexus AI Alumni Intelligence Platform"
_ENVIRONMENT = os.getenv("ENVIRONMENT")

# Rate limiting is process-local. This dict is not shared across uvicorn workers or
# container instances. With --workers 4, each worker maintains its own counter, so the
# effective rate limit is RATE_LIMIT_MAX * workers. Across multiple containers it
# multiplies further. Container restarts reset all counters. This is acceptable for
# demo and single-instance deployments but is not a strong abuse-prevention control.
_rate_limit_counts: dict[str, list[float]] = defaultdict(list)

# In-process request counters. Same scope as _rate_limit_counts: process-local,
# reset on restart, multiplied across workers. Exposed via GET /v1/metrics.
_requests_total: int = 0
_requests_by_status: dict[int, int] = defaultdict(int)
_errors_total: int = 0
_rate_limited_total: int = 0
_RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", "60"))
_RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", "60"))


def _require_api_key(x_api_key: str | None = Header(default=None)) -> dict | None:
    """
    Authenticate the request using the x-api-key header.

    DB mode (DATABASE_PATH is active and api_key_repo is on app.state):
        Verifies the key against the api_keys table.  Returns a dict with
        {"key_id", "user_id", "username"} on success.

    Env-var fallback (CSV mode or no api_key_repo):
        Compares x_api_key directly against the API_KEY env-var string,
        identical to the original behaviour.  Returns None on success.

    Both paths raise 401 with the same detail string on failure so that
    callers cannot distinguish the authentication mode from error responses.
    """
    api_key_repo: ApiKeyRepository | None = getattr(app.state, "api_key_repo", None)
    if api_key_repo is not None:
        if x_api_key is None:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        result = api_key_repo.verify_key(x_api_key)
        if result is None:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
        return result
    # Env-var fallback — unchanged behaviour from original implementation.
    if x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")
    return None


_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get()
        return True


_json_handler = logging.StreamHandler()
_json_handler.setFormatter(
    jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s")
)
_json_handler.addFilter(_RequestIdFilter())
logging.root.setLevel(logging.INFO)
logging.root.handlers = [_json_handler]

logger = logging.getLogger(__name__)


class MatchRequest(BaseModel):
    skills: list[str] = Field(default=[], max_length=50)
    interests: list[str] = Field(default=[], max_length=50)
    location: str | None = None
    limit: int | None = Field(default=None, ge=1, le=100)
    offset: int = Field(default=0, ge=0)

    @field_validator("skills", "interests", mode="before")
    @classmethod
    def _strip_and_reject_empty(cls, v):
        if not isinstance(v, list):
            return v
        result = []
        for item in v:
            if not isinstance(item, str):
                result.append(item)
                continue
            stripped = item.strip()
            if not stripped:
                raise ValueError("items must not be empty or whitespace-only")
            result.append(stripped)
        return result


class CreateAlumniRequest(BaseModel):
    alumni_id: str
    full_name: str
    email: str
    skills: list[str] = Field(default=[], max_length=50)
    interests: list[str] = Field(default=[], max_length=50)
    location: str
    engagement_score: float = Field(ge=0.0, le=1.0)
    availability: str

    @field_validator("alumni_id", "full_name", "location", "availability", mode="before")
    @classmethod
    def _strip_and_reject_empty_str(cls, v):
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("must not be empty or whitespace-only")
            return stripped
        return v

    @field_validator("email", mode="before")
    @classmethod
    def _validate_email(cls, v):
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("must not be empty or whitespace-only")
            if "@" not in stripped:
                raise ValueError("must be a valid email address")
            return stripped
        return v

    @field_validator("skills", "interests", mode="before")
    @classmethod
    def _normalize_list(cls, v):
        if not isinstance(v, list):
            return v
        result = []
        for item in v:
            if not isinstance(item, str):
                result.append(item)
                continue
            stripped = item.strip()
            if not stripped:
                raise ValueError("items must not be empty or whitespace-only")
            result.append(stripped.lower())
        return result


class UpdateAlumniRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    full_name: str
    email: str
    skills: list[str] = Field(default=[], max_length=50)
    interests: list[str] = Field(default=[], max_length=50)
    location: str
    engagement_score: float = Field(ge=0.0, le=1.0)
    availability: str

    @field_validator("full_name", "location", "availability", mode="before")
    @classmethod
    def _strip_and_reject_empty_str(cls, v):
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("must not be empty or whitespace-only")
            return stripped
        return v

    @field_validator("email", mode="before")
    @classmethod
    def _validate_email(cls, v):
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("must not be empty or whitespace-only")
            if "@" not in stripped:
                raise ValueError("must be a valid email address")
            return stripped
        return v

    @field_validator("skills", "interests", mode="before")
    @classmethod
    def _normalize_list(cls, v):
        if not isinstance(v, list):
            return v
        result = []
        for item in v:
            if not isinstance(item, str):
                result.append(item)
                continue
            stripped = item.strip()
            if not stripped:
                raise ValueError("items must not be empty or whitespace-only")
            result.append(stripped.lower())
        return result


class RankedAlumni(BaseModel):
    alumni_id: str
    full_name: str
    email: str
    skills: list[str]
    interests: list[str]
    location: str
    engagement_score: float
    availability: str
    total_score: float
    confidence_score: float
    matched_on: list[str]


class MatchResponse(BaseModel):
    count: int
    limit: int | None = None
    offset: int = 0
    results: list[RankedAlumni]


class AlumniProfile(BaseModel):
    alumni_id: str
    full_name: str
    email: str
    skills: list[str]
    interests: list[str]
    location: str
    engagement_score: float
    availability: str


class AlumniListResponse(BaseModel):
    count: int
    limit: int | None = None
    offset: int = 0
    results: list[AlumniProfile]


class CreateUserRequest(BaseModel):
    username: str

    @field_validator("username", mode="before")
    @classmethod
    def _strip_and_reject_empty(cls, v):
        if isinstance(v, str):
            stripped = v.strip()
            if not stripped:
                raise ValueError("must not be empty or whitespace-only")
            return stripped
        return v


class CreateUserResponse(BaseModel):
    user_id: str
    username: str


def _bootstrap_env_api_key(api_key_repo: "ApiKeyRepository") -> None:
    """
    Seed the API_KEY env-var value into the api_keys table on first startup.

    If verify_key() succeeds for _API_KEY the key is already present —
    nothing to do.  Otherwise create the "_env_bootstrap" system user (if it
    does not already exist) and insert the key so that existing clients and
    test suites that pass the env-var value continue to authenticate without
    any change.

    Failures are logged and swallowed: a broken bootstrap must not prevent
    the application from starting.
    """
    try:
        if api_key_repo.verify_key(_API_KEY) is not None:
            return  # already seeded — idempotent
        try:
            user_info = api_key_repo.create_user("_env_bootstrap")
        except ValueError:
            # User row already exists from a previous startup; re-query it.
            import sqlite3 as _sqlite3
            con = _sqlite3.connect(api_key_repo._db_path)
            try:
                row = con.execute(
                    "SELECT user_id FROM users WHERE username = ?",
                    ("_env_bootstrap",),
                ).fetchone()
            finally:
                con.close()
            if row is None:
                logger.warning("api_key_bootstrap: _env_bootstrap user not found after IntegrityError")
                return
            user_info = {"user_id": row[0]}
        api_key_repo.create_key(
            user_info["user_id"],
            description="bootstrapped from API_KEY env var",
            raw_key=_API_KEY,
        )
        logger.info("api_key_bootstrap: API_KEY seeded into database")
    except Exception as exc:
        logger.warning("api_key_bootstrap: could not seed API_KEY: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import os as _os
    if DATABASE_PATH and _os.path.exists(DATABASE_PATH):
        repo = SqliteAlumniRepository(DATABASE_PATH)
        # Phase 1 DB-backed auth: attach an ApiKeyRepository and ensure the
        # API_KEY env-var value is seeded as a hashed key row so that existing
        # deployments continue to work without any operator action.
        api_key_repo = ApiKeyRepository(DATABASE_PATH)
        app.state.api_key_repo = api_key_repo
        _bootstrap_env_api_key(api_key_repo)
    else:
        repo = CsvAlumniRepository(DATA_PATH)
        app.state.api_key_repo = None
    app.state.repo = repo
    # app.state.profiles is retained for backward compatibility: existing tests
    # and the health endpoint read this attribute directly.
    app.state.profiles = repo.get_all_alumni()
    yield


app = FastAPI(
    title="Colaberry Nexus AI Alumni Intelligence Platform",
    version="0.1.0",
    description="API for ranking alumni mentors based on skills, interests, location, and engagement signals.",
    lifespan=lifespan,
)


router = APIRouter(prefix="/v1")


@app.exception_handler(HTTPException)
async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.status_code, "message": exc.detail, "request_id": request_id}},
    )


@app.exception_handler(RequestValidationError)
async def _validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "-")
    return JSONResponse(
        status_code=422,
        content={"error": {"code": 422, "message": "Validation error", "request_id": request_id}},
    )


@app.middleware("http")
async def _request_id_middleware(request: Request, call_next):
    global _requests_total, _errors_total
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    token = _request_id_ctx.set(request_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        _request_id_ctx.reset(token)
    elapsed_ms = (time.perf_counter() - start) * 1000
    _requests_total += 1
    _requests_by_status[response.status_code] += 1
    if response.status_code >= 400:
        _errors_total += 1
    logger.info(
        "method=%s path=%s status_code=%d elapsed_ms=%.2f",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    response.headers["X-Request-ID"] = request_id
    return response


@app.middleware("http")
async def _rate_limit_middleware(request: Request, call_next):
    # In DB mode: use key_id as the rate-limit bucket so that the bucket is
    # stable under key rotation and is not the raw credential value.  The
    # lookup uses only the key prefix (no scrypt) so it is lightweight.
    # In env-var fallback mode: use the raw header value, identical to the
    # original behaviour.
    raw_key = request.headers.get("x-api-key") or ""
    api_key_repo: ApiKeyRepository | None = getattr(app.state, "api_key_repo", None)
    if api_key_repo is not None and raw_key:
        from src.api_key_repository import _key_prefix as _kp
        bucket = api_key_repo.get_key_id_by_prefix(_kp(raw_key)) or "anonymous"
    else:
        bucket = raw_key or "anonymous"

    now = time.time()
    window_start = now - _RATE_LIMIT_WINDOW
    timestamps = _rate_limit_counts[bucket]
    _rate_limit_counts[bucket] = [t for t in timestamps if t > window_start]
    if len(_rate_limit_counts[bucket]) >= _RATE_LIMIT_MAX:
        global _rate_limited_total
        _rate_limited_total += 1
        return JSONResponse(
            status_code=429,
            content={"error": {"code": 429, "message": "Rate limit exceeded", "request_id": "-"}},
        )
    _rate_limit_counts[bucket].append(now)
    return await call_next(request)


def _get_profiles():
    profiles = getattr(app.state, "profiles", None)
    if profiles is None:
        profiles = load_alumni_profiles_csv(DATA_PATH)
        app.state.profiles = profiles
    return profiles


@router.get(
    "/health",
    summary="Service health check",
    description="Returns the health status of the API service. Used for monitoring and readiness checks.",
    tags=["System"],
)
def health():
    profiles = getattr(app.state, "profiles", None)
    if profiles is None:
        return JSONResponse(
            status_code=503,
            content={"status": "error", "detail": "profiles not loaded"},
        )
    return {"status": "ok", "profiles_loaded": len(profiles)}


@router.get(
    "/alumni",
    response_model=AlumniListResponse,
    summary="List alumni profiles",
    description="Returns paginated alumni profiles from the dataset without ranking.",
    tags=["Alumni"],
    dependencies=[Depends(_require_api_key)],
)
def list_alumni(
    limit: int | None = Query(default=None, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    profiles = _get_profiles()

    results = profiles[offset:]
    if limit is not None:
        results = results[:limit]

    return {
        "count": len(results),
        "limit": limit,
        "offset": offset,
        "results": results,
    }


@router.get(
    "/alumni/{alumni_id}",
    response_model=AlumniProfile,
    summary="Get a single alumni profile",
    description="Returns a single alumni profile by ID.",
    tags=["Alumni"],
    dependencies=[Depends(_require_api_key)],
)
def get_alumni(alumni_id: str):
    repo = getattr(app.state, "repo", None)
    if repo is not None:
        profile = repo.get_alumni_by_id(alumni_id)
    else:
        # Fallback for contexts where lifespan did not run (e.g. module-level
        # TestClient without a context manager).
        profiles = _get_profiles()
        profile = next((p for p in profiles if p["alumni_id"] == alumni_id), None)
    if profile is None:
        raise HTTPException(status_code=404, detail="Alumni not found")
    return profile


@router.post(
    "/alumni",
    response_model=AlumniProfile,
    status_code=201,
    summary="Create a new alumni profile",
    description=(
        "Persists a new alumni profile to the database. "
        "Requires a DB-backed deployment (DATABASE_PATH must be set). "
        "Returns 503 when the active data source is read-only (CSV mode)."
    ),
    tags=["Alumni"],
    dependencies=[Depends(_require_api_key)],
)
def create_alumni_profile(body: CreateAlumniRequest):
    repo = getattr(app.state, "repo", None)
    if repo is None:
        # Lifespan did not run (e.g. module-level TestClient). Treat as CSV mode.
        raise HTTPException(
            status_code=503,
            detail=(
                "CsvAlumniRepository is read-only. "
                "Set DATABASE_PATH to a seeded SQLite database to enable writes."
            ),
        )
    try:
        profile = repo.create_alumni(body.model_dump())
    except NotImplementedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except AlumniAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Conflict: {exc.field} already exists",
        )
    return profile


@router.put(
    "/alumni/{alumni_id}",
    response_model=AlumniProfile,
    status_code=200,
    summary="Replace an alumni profile",
    description=(
        "Fully replaces the mutable fields of the alumni identified by alumni_id. "
        "alumni_id is immutable and must not be included in the request body. "
        "Requires a DB-backed deployment (DATABASE_PATH must be set). "
        "Returns 503 in CSV mode."
    ),
    tags=["Alumni"],
    dependencies=[Depends(_require_api_key)],
)
def update_alumni_profile(alumni_id: str, body: UpdateAlumniRequest):
    repo = getattr(app.state, "repo", None)
    if repo is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "CsvAlumniRepository is read-only. "
                "Set DATABASE_PATH to a seeded SQLite database to enable writes."
            ),
        )
    try:
        profile = repo.update_alumni(alumni_id, body.model_dump())
    except AlumniNotFoundError:
        raise HTTPException(status_code=404, detail="Alumni not found")
    except NotImplementedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except AlumniAlreadyExistsError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"Conflict: {exc.field} already exists",
        )
    return profile


@router.delete(
    "/alumni/{alumni_id}",
    status_code=204,
    summary="Delete an alumni profile",
    description=(
        "Permanently removes the alumni identified by alumni_id. "
        "Requires a DB-backed deployment (DATABASE_PATH must be set). "
        "Returns 503 in CSV mode."
    ),
    tags=["Alumni"],
    dependencies=[Depends(_require_api_key)],
)
def delete_alumni_profile(alumni_id: str):
    repo = getattr(app.state, "repo", None)
    if repo is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "CsvAlumniRepository is read-only. "
                "Set DATABASE_PATH to a seeded SQLite database to enable writes."
            ),
        )
    try:
        repo.delete_alumni(alumni_id)
    except AlumniNotFoundError:
        raise HTTPException(status_code=404, detail="Alumni not found")
    except NotImplementedError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    # Rebuild app.state.profiles from the updated repository cache.
    # delete_alumni() replaces self._profiles with a new list object, so
    # app.state.profiles must be reassigned (unlike create/update which
    # mutate the existing list in place).
    app.state.profiles = repo.get_all_alumni()
    return Response(status_code=204)


@router.post(
    "/users",
    response_model=CreateUserResponse,
    status_code=201,
    summary="Create a user account",
    description=(
        "Creates a named user account that can own API keys. "
        "Requires a DB-backed deployment (DATABASE_PATH must be set). "
        "Returns 503 in CSV mode."
    ),
    tags=["Auth"],
    dependencies=[Depends(_require_api_key)],
)
def create_user(body: CreateUserRequest):
    api_key_repo = getattr(app.state, "api_key_repo", None)
    if api_key_repo is None:
        raise HTTPException(
            status_code=503,
            detail=(
                "ApiKeyRepository is unavailable. "
                "Set DATABASE_PATH to a seeded SQLite database to enable user management."
            ),
        )
    try:
        return api_key_repo.create_user(body.username)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@router.post(
    "/match",
    response_model=MatchResponse,
    summary="Rank alumni mentors for a candidate",
    description="Returns ranked alumni matches based on skills, interests, location, and engagement score. Supports pagination using limit and offset parameters.",
    tags=["Matching"],
    dependencies=[Depends(_require_api_key)],
)
def match(request: MatchRequest):
    profiles = _get_profiles()

    start = time.perf_counter()
    results = rank_alumni(request.model_dump(), profiles)

    if request.offset:
        results = results[request.offset:]

    if request.limit:
        results = results[: request.limit]

    elapsed_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "match: profiles_loaded=%d ranked=%d elapsed_ms=%.2f",
        len(profiles),
        len(results),
        elapsed_ms,
    )

    return {
        "count": len(results),
        "limit": request.limit,
        "offset": request.offset,
        "results": results,
    }


@router.get(
    "/version",
    summary="Service version",
    description="Returns the service name, version, and environment. No authentication required.",
    tags=["System"],
)
def version():
    payload = {"service": _SERVICE_NAME, "version": _SERVICE_VERSION}
    if _ENVIRONMENT:
        payload["environment"] = _ENVIRONMENT
    return payload


@router.get(
    "/metrics",
    summary="In-process request counters",
    description="Returns cumulative request counters since last process start. No authentication required. Counters are process-local and reset on restart.",
    tags=["System"],
)
def metrics():
    return {
        "requests_total": _requests_total,
        "requests_by_status": dict(_requests_by_status),
        "errors_total": _errors_total,
        "rate_limited_total": _rate_limited_total,
    }


app.include_router(router)
