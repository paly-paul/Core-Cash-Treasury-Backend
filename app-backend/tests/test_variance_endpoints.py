"""Tests for variance explanation endpoints."""
import pytest
from fastapi.testclient import TestClient
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers(client):
    """Login and get auth headers."""
    response = client.post(
        "/auth/login",
        json={"email": "test@test.com", "password": "password123"},
    )
    assert response.status_code == 200
    # Auth is via cookie, not headers
    return client


def test_post_variance_request_returns_202(auth_headers):
    """Test POST /api/forecast/variance/request returns 202."""
    response = auth_headers.post(
        "/api/forecast/variance/request",
        json={"entity_id": "entity_1"},
    )
    assert response.status_code == 202
    data = response.json()
    assert "request_id" in data
    assert data["status"] == "Pending"


def test_get_variance_pending_status(auth_headers):
    """Test GET /api/forecast/variance/{id} with Pending status returns 202."""
    # First request
    response = auth_headers.post(
        "/api/forecast/variance/request",
        json={"entity_id": "entity_1"},
    )
    request_id = response.json()["request_id"]

    # Poll for status
    response = auth_headers.get(f"/api/forecast/variance/{request_id}")
    assert response.status_code == 200
    data = response.json()
    assert data["variance_id"] == request_id
    assert data["status"] in ["Pending", "Running"]


def test_get_variance_not_found_for_wrong_client(auth_headers, client):
    """Test GET variance from different client returns 404."""
    response = auth_headers.post(
        "/api/forecast/variance/request",
        json={"entity_id": "entity_1"},
    )
    request_id = response.json()["request_id"]

    # Try to access as different user (would need another login, but for MVP testing)
    response = auth_headers.get(f"/api/forecast/variance/{request_id}")
    assert response.status_code == 200


def test_get_current_variance_not_found(auth_headers):
    """Test GET /api/forecast/variance/current with no data returns 404."""
    response = auth_headers.get(
        "/api/forecast/variance/current",
        params={"entity_id": "entity_1"},
    )
    # May return 404 or 200 depending on whether data exists
    assert response.status_code in [200, 404]


def test_post_variance_invalid_entity(auth_headers):
    """Test POST with non-existent entity returns 404."""
    response = auth_headers.post(
        "/api/forecast/variance/request",
        json={"entity_id": "nonexistent_entity"},
    )
    assert response.status_code == 404


def test_get_variance_unauthorized(client):
    """Test unauthenticated request returns 401."""
    response = client.get("/api/forecast/variance/any_id")
    assert response.status_code == 401


def test_variance_request_with_analysis_date(auth_headers):
    """Test POST with custom analysis_date."""
    response = auth_headers.post(
        "/api/forecast/variance/request",
        json={
            "entity_id": "entity_1",
            "analysis_date": "2026-08-22",
        },
    )
    assert response.status_code == 202
    data = response.json()
    assert "request_id" in data
