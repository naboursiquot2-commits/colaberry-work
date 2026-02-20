import pytest

from src.matching_engine import rank_alumni


def test_rank_alumni_returns_sorted_results_with_scores():
    """
    Basic contract test:
    - returns a list
    - includes total_score and confidence_score
    - confidence_score == total_score
    - total_score bounded 0..1
    - alumni_id preserved
    """
    request = {
        "skills": ["python"],
        "interests": ["mentorship"],
        "location": "NY",
    }

    alumni_profiles = [
        {
            "alumni_id": "A001",
            "full_name": "Jane Doe",
            "email": "jane@example.com",
            "skills": ["python"],
            "interests": ["mentorship"],
            "location": "NY",
            "engagement_score": 0.8,
            "availability": "mentor",
        }
    ]

    results = rank_alumni(request, alumni_profiles)

    # Check result structure
    assert isinstance(results, list)
    assert len(results) == 1

    first = results[0]

    # Check identity preserved
    assert first["alumni_id"] == "A001"

    # Check scoring fields exist
    assert "total_score" in first
    assert "confidence_score" in first

    # confidence_score must equal total_score
    assert first["confidence_score"] == first["total_score"]

    # Score must be within valid bounds
    assert 0.0 <= first["total_score"] <= 1.0


def test_rank_alumni_basic_scoring():
    """
    Behavioral scoring scenario (Alice vs Bob):
    - Alice should rank first
    - Alice total_score == 1.0
    - Bob total_score == 0.0
    - results sorted descending by total_score
    """

    request = {
        "skills": ["python", "sql"],
        "interests": ["mentorship"],
        "location": "NY",
    }

    alumni_profiles = [
        {
            "alumni_id": "1",
            "full_name": "Alice",
            "email": "alice@example.com",
            "skills": ["python", "sql"],
            "interests": ["mentorship"],
            "location": "NY",
            "engagement_score": 1.0,
            "availability": "mentor",
        },
        {
            "alumni_id": "2",
            "full_name": "Bob",
            "email": "bob@example.com",
            "skills": ["excel"],
            "interests": ["finance"],
            "location": "CA",
            "engagement_score": 0.0,
            "availability": "mentor",
        },
    ]

    results = rank_alumni(request, alumni_profiles)

    # Verify results sorted descending
    scores = [r["total_score"] for r in results]
    assert scores == sorted(scores, reverse=True)

    # Alice should be first
    assert results[0]["alumni_id"] == "1"

    # Bob should be second
    assert results[1]["alumni_id"] == "2"

    # Verify exact scores
    alice = next(r for r in results if r["alumni_id"] == "1")
    bob = next(r for r in results if r["alumni_id"] == "2")

    assert alice["total_score"] == 1.0
    assert bob["total_score"] == 0.0
