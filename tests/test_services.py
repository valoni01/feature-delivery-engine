from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from app.services.models import Service


def _make_service(**overrides) -> Service:
    """Helper to create a fake Service with sensible defaults."""
    defaults = {
        "id": 1,
        "name": "Auth Service",
        "slug": "auth-service",
        "description": "Handles authentication",
        "department": "platform",
        "is_active": True,
        "created_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
    }
    defaults.update(overrides)
    service = Service(**defaults)
    return service


class TestCreateService:
    async def test_create_service_success(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute.return_value = mock_result

        created = _make_service()
        mock_db.refresh.side_effect = lambda obj: _apply_defaults(obj, created)

        response = await client.post("/api/v1/services", json={
            "name": "Auth Service",
            "slug": "auth-service",
            "description": "Handles authentication",
            "department": "platform",
        })

        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Auth Service"
        assert data["slug"] == "auth-service"
        mock_db.add.assert_called_once()
        mock_db.commit.assert_awaited_once()

    async def test_create_service_duplicate_slug(self, client, mock_db):
        existing = _make_service()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = existing
        mock_db.execute.return_value = mock_result

        response = await client.post("/api/v1/services", json={
            "name": "Auth Service",
            "slug": "auth-service",
        })

        assert response.status_code == 409
        assert "already exists" in response.json()["detail"]
        mock_db.add.assert_not_called()

    async def test_create_service_missing_name(self, client):
        response = await client.post("/api/v1/services", json={
            "slug": "auth-service",
        })

        assert response.status_code == 422

    async def test_create_service_empty_slug(self, client):
        response = await client.post("/api/v1/services", json={
            "name": "Auth Service",
            "slug": "",
        })

        assert response.status_code == 422


class TestGetService:
    async def test_get_service_found(self, client, mock_db):
        service = _make_service()
        mock_db.get.return_value = service

        response = await client.get("/api/v1/services/1")

        assert response.status_code == 200
        data = response.json()
        assert data["id"] == 1
        assert data["slug"] == "auth-service"

    async def test_get_service_not_found(self, client, mock_db):
        mock_db.get.return_value = None

        response = await client.get("/api/v1/services/999")

        assert response.status_code == 404
        assert "not found" in response.json()["detail"].lower()


class TestListServices:
    async def test_list_services(self, client, mock_db):
        services = [_make_service(id=1, name="A"), _make_service(id=2, name="B")]
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = services
        mock_db.execute.return_value = mock_result

        response = await client.get("/api/v1/services")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    async def test_list_services_empty(self, client, mock_db):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute.return_value = mock_result

        response = await client.get("/api/v1/services")

        assert response.status_code == 200
        assert response.json() == []


class TestUpdateService:
    async def test_update_service_success(self, client, mock_db):
        service = _make_service()
        mock_db.get.return_value = service

        response = await client.patch("/api/v1/services/1", json={
            "name": "Auth Service v2",
        })

        assert response.status_code == 200
        assert service.name == "Auth Service v2"
        mock_db.commit.assert_awaited_once()

    async def test_update_service_not_found(self, client, mock_db):
        mock_db.get.return_value = None

        response = await client.patch("/api/v1/services/999", json={
            "name": "Nope",
        })

        assert response.status_code == 404


class TestDeactivateService:
    async def test_deactivate_service_success(self, client, mock_db):
        service = _make_service(is_active=True)
        mock_db.get.return_value = service

        response = await client.delete("/api/v1/services/1")

        assert response.status_code == 204
        assert service.is_active is False
        mock_db.commit.assert_awaited_once()

    async def test_deactivate_service_not_found(self, client, mock_db):
        mock_db.get.return_value = None

        response = await client.delete("/api/v1/services/999")

        assert response.status_code == 404


def _apply_defaults(obj: Service, template: Service) -> None:
    """Simulates what db.refresh does — copies computed fields onto the object."""
    obj.id = template.id
    obj.created_at = template.created_at
    obj.updated_at = template.updated_at
