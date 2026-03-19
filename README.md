# Colaberry Nexus AI Alumni Intelligence Platform

![Python](https://img.shields.io/badge/python-3.11+-blue)
![FastAPI](https://img.shields.io/badge/framework-FastAPI-green)
![Tests](https://img.shields.io/badge/tests-pytest-blue)
![CI](https://img.shields.io/badge/CI-GitHub%20Actions-success)

## Overview

A deterministic AI-powered service that ranks alumni mentors based on skills, interests, location, and engagement signals.

This project demonstrates a production-style API architecture including:

- FastAPI service layer
- Deterministic ranking engine
- Structured API contracts
- Automated testing with pytest
- Continuous integration with GitHub Actions
- Environment configuration
- OpenAPI / Swagger documentation

---

## Architecture Overview

The system is structured as a layered architecture.

Client Application
│
▼
FastAPI API Layer
│
▼
Matching Engine
│
▼
Alumni Dataset (CSV)

### FastAPI API Layer

- Handles authentication, validation, and routing
- Exposes versioned endpoints (/v1)
- Provides OpenAPI / Swagger documentation

### Matching Engine

- Scores alumni mentors using skills, interests, location, and engagement signals
- Produces deterministic ranking results

### Dataset Loader

- Loads the CSV alumni dataset at service startup
- Caches profiles in memory for fast ranking queries

---

# Runbook

## Prerequisites

Python 3.11+

Git

Virtual environment support

Optional:
Docker (for containerized deployment)

---

## Setup

Clone the repository

git clone https://github.com/naboursiquot2-commits/colaberry-work.git
cd colaberry-work

Create a virtual environment

python -m venv .venv

Activate the virtual environment

.venv\Scripts\activate

Install dependencies

pip install -r requirements.txt

---

## Environment Configuration

Create a .env file in the project root.

Example configuration:

API_KEY=dev-secret-key  
DATA_PATH=data/sample_alumni.csv

Notes:

- .env files should never be committed
- API_KEY secures access to the API
- DATA_PATH defines the dataset location

---

## Running the API

Start the FastAPI development server

uvicorn src.api:app --reload

The API will run at:

http://localhost:8000

Interactive API documentation:

http://localhost:8000/docs

Alternative documentation:

http://localhost:8000/redoc

---

## API Endpoints

GET /v1/health  
Service health check

POST /v1/match  
Rank alumni mentors

GET /v1/alumni
List alumni profiles with pagination

GET /v1/alumni/{alumni_id}
Get a single alumni profile by ID

---

## Example Requests

Health Check

curl -X GET http://localhost:8000/v1/health

Response

{
  "status": "ok"
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

---

## Common Commands

Run the full test suite

python -m pytest

Run tests with verbose output

python -m pytest -v

Run only API tests

python -m pytest tests/test_api.py

Run only matching engine tests

python -m pytest tests/test_matching_engine.py

---

## Docker

Build the container

docker build -t alumni-api .

Run the container

docker run -p 8000:8000 alumni-api

Access the API documentation

http://localhost:8000/docs

---

## Continuous Integration

This repository includes a GitHub Actions CI pipeline.

The pipeline automatically:

- installs dependencies
- runs the pytest test suite
- validates API functionality

This ensures new changes do not break existing features.

---

## Project Structure

colaberry-work

src/
api.py  
matching_engine.py  

tests/
test_api.py  
test_api_integration.py  
test_matching_engine.py  

data/
sample_alumni.csv  

docs/
api_examples.md  

directives/
api_contract.md  

.github/workflows/
ci.yml  

Dockerfile  
requirements.txt  
README.md  

---

## Future Improvements

- database-backed alumni storage
- semantic skill matching
- machine learning ranking models
- recommendation feedback loops
- observability metrics
- cloud deployment

---

## Notes

- API authentication uses the x-api-key header
- Pagination uses limit and offset
- Alumni profiles are loaded from CSV and cached at service startup
- The service is designed as a lightweight microservice architecture
- Match results include explainability via matched_on — each result reports which signals (skills, interests, location) contributed to the match
