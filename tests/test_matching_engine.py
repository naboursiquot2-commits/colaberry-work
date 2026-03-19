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


def test_rank_alumni_empty_request_skills_and_interests():
    """
    When the request has empty skills and interests, both Jaccard similarity
    components must be 0.0. Only location and engagement can contribute.

    Formula with all Jaccard = 0, location match = 1.0, engagement = 0.0:
        total = 0.45*0 + 0.25*0 + 0.10*1.0 + 0.20*0.0 = 0.10
    """
    request = {
        "skills": [],
        "interests": [],
        "location": "NY",
    }
    alumni_profiles = [
        {
            "alumni_id": "E001",
            "full_name": "Empty Request User",
            "email": "empty_req@example.com",
            "skills": ["python", "sql"],
            "interests": ["mentorship"],
            "location": "NY",
            "engagement_score": 0.0,
            "availability": "mentor",
        }
    ]

    results = rank_alumni(request, alumni_profiles)

    assert len(results) == 1
    result = results[0]
    assert result["total_score"] == pytest.approx(0.10)
    assert result["confidence_score"] == pytest.approx(0.10)


def test_rank_alumni_profile_empty_skills_and_interests_no_zero_division():
    """
    Profiles with empty skills and interests must not raise ZeroDivisionError.
    The _jaccard helper guards against empty union explicitly.

    Formula with Jaccard = 0, location match = 1.0, engagement = 0.5:
        total = 0.45*0 + 0.25*0 + 0.10*1.0 + 0.20*0.5 = 0.20
    """
    request = {
        "skills": ["python"],
        "interests": ["mentorship"],
        "location": "NY",
    }
    alumni_profiles = [
        {
            "alumni_id": "E002",
            "full_name": "No Skills User",
            "email": "noskills@example.com",
            "skills": [],
            "interests": [],
            "location": "NY",
            "engagement_score": 0.5,
            "availability": "mentor",
        }
    ]

    results = rank_alumni(request, alumni_profiles)

    assert len(results) == 1
    result = results[0]
    assert result["total_score"] == pytest.approx(0.20)


def test_rank_alumni_missing_location_in_request_no_bonus():
    """
    When location is absent from the request dict, request.get('location', '')
    returns '' which is falsy — so location_bonus must be 0.0.

    Formula with skills/interests fully matched, location bonus = 0, engagement = 0:
        total = 0.45*1.0 + 0.25*1.0 + 0.10*0.0 + 0.20*0.0 = 0.70
    """
    request = {
        "skills": ["python"],
        "interests": ["mentorship"],
        # location key intentionally omitted
    }
    alumni_profiles = [
        {
            "alumni_id": "E003",
            "full_name": "Located Alumni",
            "email": "located@example.com",
            "skills": ["python"],
            "interests": ["mentorship"],
            "location": "NY",
            "engagement_score": 0.0,
            "availability": "mentor",
        }
    ]

    results = rank_alumni(request, alumni_profiles)

    assert len(results) == 1
    result = results[0]
    assert result["total_score"] == pytest.approx(0.70)


def test_rank_alumni_missing_engagement_defaults_to_zero():
    """
    When engagement_score is absent from a profile, alumni.get('engagement_score', 0.0)
    must default to 0.0 without raising a KeyError.

    Formula with full skill/interest/location match, engagement = 0.0 (default):
        total = 0.45*1.0 + 0.25*1.0 + 0.10*1.0 + 0.20*0.0 = 0.80
    """
    request = {
        "skills": ["python"],
        "interests": ["mentorship"],
        "location": "NY",
    }
    alumni_profiles = [
        {
            "alumni_id": "E004",
            "full_name": "No Engagement User",
            "email": "noeng@example.com",
            "skills": ["python"],
            "interests": ["mentorship"],
            "location": "NY",
            # engagement_score key intentionally omitted
            "availability": "mentor",
        }
    ]

    results = rank_alumni(request, alumni_profiles)

    assert len(results) == 1
    result = results[0]
    assert result["total_score"] == pytest.approx(0.80)


def test_rank_alumni_matched_on_includes_all_signals():
    """
    When skills, interests, and location all match, matched_on must contain
    all three signals: "skills", "interests", "location".
    """
    request = {
        "skills": ["python"],
        "interests": ["mentorship"],
        "location": "NY",
    }
    alumni_profiles = [
        {
            "alumni_id": "T001",
            "full_name": "Test Alumni",
            "email": "test@example.com",
            "skills": ["python"],
            "interests": ["mentorship"],
            "location": "NY",
            "engagement_score": 0.5,
            "availability": "mentor",
        }
    ]

    results = rank_alumni(request, alumni_profiles)

    assert len(results) == 1
    matched_on = results[0]["matched_on"]
    assert "skills" in matched_on
    assert "interests" in matched_on
    assert "location" in matched_on


def test_rank_alumni_matched_on_does_not_include_engagement():
    """
    matched_on must never include "engagement" — engagement contributes to
    total_score but is not a match signal.
    """
    request = {
        "skills": ["python"],
        "interests": ["mentorship"],
        "location": "NY",
    }
    alumni_profiles = [
        {
            "alumni_id": "T002",
            "full_name": "Test Alumni",
            "email": "test@example.com",
            "skills": ["python"],
            "interests": ["mentorship"],
            "location": "NY",
            "engagement_score": 1.0,
            "availability": "mentor",
        }
    ]

    results = rank_alumni(request, alumni_profiles)

    assert len(results) == 1
    assert "engagement" not in results[0]["matched_on"]


def test_rank_alumni_performance_1000_profiles():
    """
    Performance test: rank_alumni must process 1,000 synthetic profiles in under 2.0s.

    Profiles are generated in-memory with a fixed random seed so the test is
    fully deterministic across runs. Skills and interests are drawn from fixed
    pools using random.sample to avoid duplicates.
    """
    import random
    import time

    random.seed(42)

    SKILLS_POOL = [
        "python", "sql", "java", "javascript", "typescript", "react", "excel",
        "tableau", "powerbi", "machine learning", "data analysis", "tensorflow",
        "pandas", "numpy", "spark", "aws", "azure", "docker", "kubernetes", "git",
    ]
    INTERESTS_POOL = [
        "mentorship", "teaching", "research", "ai", "finance", "data visualization",
        "web development", "cloud computing", "open source", "product management",
        "entrepreneurship", "nonprofit", "healthcare", "education", "sustainability",
    ]
    LOCATIONS = ["NY", "CA", "TX", "FL", "WA"]

    profiles = [
        {
            "alumni_id": f"PERF{i:04d}",
            "full_name": f"Alumni {i}",
            "email": f"alumni{i}@example.com",
            "skills": random.sample(SKILLS_POOL, random.randint(2, 6)),
            "interests": random.sample(INTERESTS_POOL, random.randint(1, 4)),
            "location": random.choice(LOCATIONS),
            "engagement_score": round(random.uniform(0.0, 1.0), 2),
            "availability": random.choice(["mentor", "available"]),
        }
        for i in range(1000)
    ]

    request = {
        "skills": ["python", "sql", "machine learning"],
        "interests": ["mentorship", "research"],
        "location": "NY",
    }

    start = time.perf_counter()
    results = rank_alumni(request, profiles)
    elapsed = time.perf_counter() - start

    assert len(results) == 1000, f"Expected 1000 results, got {len(results)}"
    assert elapsed < 2.0, f"rank_alumni took {elapsed:.3f}s for 1,000 profiles (limit: 2.0s)"

    # Verify output is still correctly sorted
    scores = [r["total_score"] for r in results]
    assert scores == sorted(scores, reverse=True)
