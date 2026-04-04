import pytest
from fastapi.testclient import TestClient
from src.ui.api.server import app

client = TestClient(app)

def test_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert "status" in data
    assert "last_dispatch_at" in data
    assert "pending_count" in data
    assert "error_count" in data
    assert "poll_interval_seconds" in data
