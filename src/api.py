import logging
import os
import time

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel

from src.matching_engine import load_alumni_profiles_csv, rank_alumni

_API_KEY = os.getenv("API_KEY", "dev-secret-key")


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
    limit: int | None = None
    offset: int = 0


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


app = FastAPI(
    title="Colaberry Nexus AI Alumni Intelligence Platform",
    version="0.1.0",
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post(
    "/match",
    response_model=list[RankedAlumni],
    dependencies=[Depends(_require_api_key)],
)
def match(request: MatchRequest):
    profiles = load_alumni_profiles_csv("data/sample_alumni.csv")

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
    return results