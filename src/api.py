import logging
import os
import time
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field

from src.matching_engine import load_alumni_profiles_csv, rank_alumni

_API_KEY = os.getenv("API_KEY", "dev-secret-key")
DATA_PATH = os.getenv("DATA_PATH", "data/sample_alumni.csv")


def _require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if x_api_key != _API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
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
