Colaberry Nexus AI Alumni Intelligence Platform

Backend matching service that ranks alumni mentors against learner requests using a deterministic scoring engine, with production-ready API architecture, observability, testing, and CI/CD.

Overview

Nexus AI is a backend matching service that ranks Colaberry alumni mentors against learner requests using a deterministic scoring engine. Candidates are scored across skills, interests, location, and engagement signals — producing consistent, auditable results with no LLM involvement in the ranking logic.

The service includes production-ready backend features:

Authentication — API key enforcement via x-api-key header
Pagination — limit / offset support on match and listing endpoints
Structured logging — JSON-formatted logs
Request ID tracing — every request includes an X-Request-ID
Rate limiting — per-API-key request throttling
Structured error responses — consistent error schema
Health readiness endpoint — /v1/health reports service readiness
Explainable match results — results include matched_on
Automated testing with pytest
Continuous Integration with GitHub Actions
Test coverage enforcement in CI
Docker container support
Architecture Overview

The system is structured as a layered pipeline:

Client → API Gateway → Middleware → Matching Engine → Data Layer → Response

API Gateway
FastAPI handles routing, validation, and versioned endpoints (/v1)
API key authentication enforced on protected endpoints
OpenAPI / Swagger documentation automatically generated
Middleware
Request ID tracing
Structured JSON logging
Rate limiting per API key
Structured error handling
Matching Engine
Deterministic scoring using:
Skills overlap
Interests overlap
Location match
Engagement score
Fully auditable and reproducible results
No LLM involvement in ranking logic
Data Layer
Alumni profiles loaded from CSV at service startup
Cached in memory for low-latency ranking queries
Response Layer
Returns ranked results with:
confidence_score
matched_on (explainability signals)
Explainability

Every match result includes a matched_on field that identifies which scoring signals contributed to that candidate's ranking.

Supported signals:

skills
interests
location

This makes the ranking transparent and fully auditable — no black-box scoring.

Example result:

{
  "alumni_id": "A042",
  "confidence_score": 0.85,
  "matched_on": ["skills", "interests", "location"]
}
Observability and Production Features
Feature	Detail
Structured logging	JSON logs for all requests
Request ID tracing	X-Request-ID returned and logged
Rate limiting	Per API key throttling
Structured errors	Standard error response format
Health endpoint	/v1/health readiness check
CI/CD	Tests run on every push
Test coverage	Coverage enforced in CI
Runbook
Prerequisites
Python 3.11+
Git
Virtual environment support
Optional: Docker (for containerized deployment)
Setup

Clone the repository

git clone https://github.com/naboursiquot2-commits/colaberry-work.git
cd colaberry-work

Create a virtual environment

python -m venv .venv

Activate the virtual environment

.venv\Scripts\activate

Install dependencies

pip install -r requirements.txt
Environment Configuration

Create a .env file in the project root.

Example configuration:

API_KEY=dev-secret-key
DATA_PATH=data/sample_alumni.csv

Notes:

.env files should never be committed
API_KEY secures access to the API
DATA_PATH defines the dataset location
Running the API

Start the FastAPI development server

uvicorn src.api:app --reload

The API will run at:

http://localhost:8000

Interactive API documentation:

http://localhost:8000/docs

Alternative documentation:

http://localhost:8000/redoc
API Endpoints
Method	Endpoint	Description	Auth Required
GET	/v1/health	Service and data readiness check	No
POST	/v1/match	Rank alumni mentors	Yes
GET	/v1/alumni	List alumni profiles	Yes
GET	/v1/alumni/{alumni_id}	Get alumni profile by ID	Yes

All endpoints except /v1/health require the x-api-key header.

Example Requests
Health Check
curl -X GET http://localhost:8000/v1/health

Example response:

{
  "status": "ok",
  "profiles_loaded": 6
}
Match Alumni Mentors
curl -X POST http://localhost:8000/v1/match \
-H "Content-Type: application/json" \
-H "x-api-key: dev-secret-key" \
-d '{
  "skills": ["python"],
  "interests": ["mentorship"],
  "location": "NY"
}'
Paginated Match Request
curl -X POST http://localhost:8000/v1/match \
-H "Content-Type: application/json" \
-H "x-api-key: dev-secret-key" \
-d '{
  "skills": ["python"],
  "interests": ["mentorship"],
  "location": "NY",
  "limit": 2,
  "offset": 1
}'
Alumni Listing
curl -X GET "http://localhost:8000/v1/alumni?limit=2&offset=0" \
-H "x-api-key: dev-secret-key"
Common Commands

Run the full test suite

python -m pytest

Run tests with verbose output

python -m pytest -v

Run only API tests

python -m pytest tests/test_api.py

Run only matching engine tests

python -m pytest tests/test_matching_engine.py
Docker

Build the container

docker build -t alumni-api .

Run the container

docker run -p 8000:8000 alumni-api

Access the API documentation

http://localhost:8000/docs
Continuous Integration

This repository includes a GitHub Actions CI pipeline.

The pipeline automatically:

Installs dependencies
Runs the pytest test suite
Enforces minimum test coverage
Validates API functionality

This ensures new changes do not break existing features.

Project Structure
colaberry-work
│
├── src/
│   ├── api.py
│   └── matching_engine.py
│
├── tests/
│   ├── test_api.py
│   ├── test_api_integration.py
│   └── test_matching_engine.py
│
├── data/
│   └── sample_alumni.csv
│
├── docs/
│   └── api_examples.md
│
├── directives/
│   └── api_contract.md
│
├── .github/workflows/
│   └── ci.yml
│
├── Dockerfile
├── requirements.txt
└── README.md
Future Improvements
Database-backed alumni storage
Semantic skill matching
Machine learning ranking models
Recommendation feedback loops
Observability metrics dashboard
Cloud deployment
Notes
API authentication uses the x-api-key header
Pagination uses limit and offset
Alumni profiles are loaded from CSV and cached at service startup
The service is designed as a lightweight microservice architecture
Match results include explainability via matched_on
The ranking engine is deterministic and fully auditable
License

This project is for educational and portfolio demonstration purposes.