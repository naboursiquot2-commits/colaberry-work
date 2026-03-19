import csv
def rank_alumni(request: dict, alumni_profiles: list[dict]) -> list[dict]:
    """
    Rank alumni profiles for a given request using a deterministic scoring model.

    Expected request schema (v1):
        {
            "skills": list[str],
            "interests": list[str],
            "location": str (optional)
        }

    Expected alumni profile schema (v1):
        {
            "alumni_id": str,
            "full_name": str,
            "email": str,
            "skills": list[str],
            "interests": list[str],
            "location": str,
            "engagement_score": float (0–1 normalized),
            "availability": str
        }

    Scoring formula (v1):
        total_score =
            (0.45 * Jaccard(skills)) +
            (0.25 * Jaccard(interests)) +
            (0.10 * location_bonus) +
            (0.20 * engagement_score)

        Where:
            Jaccard(x) = |A ∩ B| / |A ∪ B|  (bounded 0–1)
            location_bonus = 1 if request.location == alumni.location, else 0

    Confidence calculation:
        confidence_score = total_score  (bounded 0–1)

    Deterministic guarantees:
        - No file I/O
        - No external API calls
        - No randomness
        - Same inputs always produce same outputs

    Output:
        Returns a list of alumni profile dicts augmented with scoring fields,
        sorted in descending order by total_score.

    Notes:
        v1 implementation — weighted Jaccard similarity with location bonus.
    """

    def _jaccard(a: list[str], b: list[str]) -> float:
        set_a = set(a)
        set_b = set(b)
        union = set_a | set_b
        if not union:
            return 0.0
        return len(set_a & set_b) / len(union)

    request_location = request.get("location", "")
    request_skills = request.get("skills", [])
    request_interests = request.get("interests", [])

    results = []
    for alumni in alumni_profiles:
        skill_score = _jaccard(request_skills, alumni.get("skills", []))
        interest_score = _jaccard(request_interests, alumni.get("interests", []))
        location_bonus = 1.0 if request_location and request_location == alumni.get("location", "") else 0.0
        engagement = alumni.get("engagement_score", 0.0)

        total_score = (
            0.45 * skill_score
            + 0.25 * interest_score
            + 0.10 * location_bonus
            + 0.20 * engagement
        )

        matched_on = []
        if skill_score > 0:
            matched_on.append("skills")
        if interest_score > 0:
            matched_on.append("interests")
        if location_bonus > 0:
            matched_on.append("location")

        results.append({
            **alumni,
            "total_score": total_score,
            "confidence_score": total_score,
            "matched_on": matched_on,
        })

    results.sort(key=lambda x: x["total_score"], reverse=True)
    return results
def load_alumni_profiles_csv(path: str) -> list[dict]:
    """
    Load alumni profiles from a CSV file and return a list of dicts matching the
    alumni schema used by rank_alumni().

    Parsing assumptions (v1):
    - skills and interests are comma-separated strings (e.g., "python, sql")
      and are converted to list[str] (lowercased, stripped).
    - engagement_score is parsed as float. If the value appears to be 0–100,
      it is normalized to 0–1 by dividing by 100.
    - Missing or invalid engagement_score values default to 0.0.
    """
    profiles: list[dict] = []

    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            skills_raw = (row.get("skills") or "")
            interests_raw = (row.get("interests") or "")

            skills = [s.strip().lower() for s in skills_raw.split(",") if s.strip()]
            interests = [i.strip().lower() for i in interests_raw.split(",") if i.strip()]

            engagement_raw = (row.get("engagement_score") or "").strip()
            try:
                engagement_score = float(engagement_raw) if engagement_raw else 0.0
            except ValueError:
                engagement_score = 0.0

            # Normalize if the value looks like 0–100 scale
            if engagement_score > 1.0:
                engagement_score = engagement_score / 100.0

            profile = {
                "alumni_id": (row.get("alumni_id") or "").strip(),
                "full_name": (row.get("full_name") or "").strip(),
                "email": (row.get("email") or "").strip(),
                "skills": skills,
                "interests": interests,
                "location": (row.get("location") or "").strip(),
                "engagement_score": engagement_score,
                "availability": (row.get("availability") or "").strip(),
            }

            profiles.append(profile)

    return profiles

