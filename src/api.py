import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from contextvars import ContextVar

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from pythonjsonlogger import json as jsonlogger

from src.matching_engine import load_alumni_profiles_csv, rank_alumni

_API_KEY = os.getenv("API_KEY", "dev-secret-key")
DATA_PATH = os.getenv("DATA_PATH", "data/sample_alumni.csv")


def _require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


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
    skills: list[str] = []
    interests: list[str] = []
    location: str | None = None
    limit: int | None = Field(default=None, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.profiles = load_alumni_profiles_csv(DATA_PATH)
    yield


app = FastAPI(
    title="Colaberry Nexus AI Alumni Intelligence Platform",
    version="0.1.0",
    description="API for ranking alumni mentors based on skills, interests, location, and engagement signals.",
    lifespan=lifespan,
)


router = APIRouter(prefix="/v1")


@app.middleware("http")
async def _request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id
    token = _request_id_ctx.set(request_id)
    start = time.perf_counter()
    try:
        response = await call_next(request)
    finally:
        _request_id_ctx.reset(token)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info(
        "method=%s path=%s status_code=%d elapsed_ms=%.2f",
        request.method,
        request.url.path,
        response.status_code,
        elapsed_ms,
    )
    response.headers["X-Request-ID"] = request_id
    return response


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
    return {"status": "ok"}


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
    profiles = _get_profiles()
    profile = next((p for p in profiles if p["alumni_id"] == alumni_id), None)
    if profile is None:
        raise HTTPException(status_code=404, detail="Alumni not found")
    return profile


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


app.include_router(router)
