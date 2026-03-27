import os

# Set a test API key before any application module is imported.
# This satisfies the startup requirement in src/api.py that API_KEY must be set.
# Uses setdefault so a real API_KEY already in the environment is never overridden.
os.environ.setdefault("API_KEY", "dev-secret-key")
