import pytest

from src.matching_engine import rank_alumni, load_alumni_profiles_csv


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


def test_load_alumni_profiles_csv_parsing():
    """
    Test CSV parsing behavior:
    - Loads correct number of rows
    - Skills are converted to lists (not strings)
    - Skills are lowercased
    - Engagement score of 75 is normalized to 0.75
    - Engagement score "N/A" is converted to 0.0
    """
    profiles = load_alumni_profiles_csv("data/sample_alumni.csv")

    # Assert number of rows loaded equals 6
    assert len(profiles) == 6

    # Assert skills are lists (not strings)
    for profile in profiles:
        assert isinstance(profile["skills"], list), f"Skills should be a list, got {type(profile['skills'])}"
        assert isinstance(profile["interests"], list), f"Interests should be a list, got {type(profile['interests'])}"

    # Assert skills are lowercase
    for profile in profiles:
        for skill in profile["skills"]:
            assert skill == skill.lower(), f"Skill '{skill}' should be lowercase"
        for interest in profile["interests"]:
            assert interest == interest.lower(), f"Interest '{interest}' should be lowercase"

    # Assert engagement_score of 75 becomes 0.75
    alice = next(p for p in profiles if p["alumni_id"] == "A001")
    assert alice["engagement_score"] == 0.75, f"Expected 0.75, got {alice['engagement_score']}"

    # Assert engagement_score "N/A" becomes 0.0
    carol = next(p for p in profiles if p["alumni_id"] == "A003")
    assert carol["engagement_score"] == 0.0, f"Expected 0.0 for N/A, got {carol['engagement_score']}"

    frank = next(p for p in profiles if p["alumni_id"] == "A006")
    assert frank["engagement_score"] == 0.0, f"Expected 0.0 for N/A, got {frank['engagement_score']}"
