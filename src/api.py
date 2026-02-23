from fastapi import FastAPI

from src.matching_engine import rank_alumni, load_alumni_profiles_csv

app = FastAPI(title="Colaberry Nexus Matching Service", version="0.1.0")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/match")
def match(request: dict):
    profiles = load_alumni_profiles_csv("data/sample_alumni.csv")
    results = rank_alumni(request, profiles)
    return results
