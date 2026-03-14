import pytest
import uuid as uuid_module
from unittest.mock import AsyncMock, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def app_with_mock_pool():
    """Create a test app that bypasses lifespan and uses a mock pool."""
    from fastapi import FastAPI
    from src.api.routes.documents import router

    app = FastAPI()
    app.include_router(router)

    mock_pool = MagicMock()
    app.state.pool = mock_pool
    return app, mock_pool


def test_get_documents_returns_list(app_with_mock_pool):
    app, mock_pool = app_with_mock_pool

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = [
        {
            "id": "abc123",
            "filename": "01_CAM6551_test.pdf",
            "foi_reference": "CAM6551",
            "date": None,
            "title": "Test doc",
            "total_pages": 2,
            "indexed_at": None,
        }
    ]
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    client = TestClient(app)
    resp = client.get("/documents")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert data[0]["filename"] == "01_CAM6551_test.pdf"
    assert data[0]["foi_reference"] == "CAM6551"


def test_get_documents_returns_empty_list(app_with_mock_pool):
    app, mock_pool = app_with_mock_pool

    mock_conn = AsyncMock()
    mock_conn.fetch.return_value = []
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    client = TestClient(app)
    resp = client.get("/documents")
    assert resp.status_code == 200
    assert resp.json() == []


def test_get_log_returns_log(app_with_mock_pool):
    app, mock_pool = app_with_mock_pool
    import uuid
    log_id = str(uuid.uuid4())
    chunk_uuid = uuid_module.uuid4()

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = {
        "id": log_id,
        "query": "test question",
        "filters": {"date_from": "None", "date_to": "None"},
        "retrieved_chunk_ids": [chunk_uuid],
        "prompt_sent": "prompt",
        "response": "answer",
        "model": "claude-sonnet-4-6",
        "queried_at": None,
    }
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    client = TestClient(app)
    resp = client.get(f"/logs/{log_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["query"] == "test question"
    assert data["model"] == "claude-sonnet-4-6"
    assert data["retrieved_chunk_ids"] == [str(chunk_uuid)]


def test_get_log_returns_404_when_not_found(app_with_mock_pool):
    app, mock_pool = app_with_mock_pool
    import uuid
    log_id = str(uuid.uuid4())

    mock_conn = AsyncMock()
    mock_conn.fetchrow.return_value = None
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

    client = TestClient(app)
    resp = client.get(f"/logs/{log_id}")
    assert resp.status_code == 404
