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

        results.append({
            **alumni,
            "total_score": total_score,
            "confidence_score": total_score,
        })

    results.sort(key=lambda x: x["total_score"], reverse=True)
    return results
