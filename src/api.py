import logging
import time

from fastapi import FastAPI
from pydantic import BaseModel

from src.matching_engine import rank_alumni, load_alumni_profiles_csv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


class MatchRequest(BaseModel):
    skills: list[str] = []
    interests: list[str] = []
    location: str | None = None


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


app = FastAPI(title="Colaberry Nexus Matching Service", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/match", response_model=list[RankedAlumni])
def match(request: MatchRequest):
    profiles = load_alumni_profiles_csv("data/sample_alumni.csv")

    start = time.perf_counter()
    results = rank_alumni(request.model_dump(), profiles)
    elapsed_ms = (time.perf_counter() - start) * 1000

    logger.info(
        "match: profiles_loaded=%d ranked=%d elapsed_ms=%.2f",
        len(profiles),
        len(results),
        elapsed_ms,
    )

    return results
