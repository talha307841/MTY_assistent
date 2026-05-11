from __future__ import annotations

import os
from datetime import datetime

from fastapi.testclient import TestClient

os.environ.setdefault("OPENAI_API_KEY", "")

from focus_daemon import app, daemon  # noqa: E402
from db.models import Task, TaskStatus  # noqa: E402


def test_create_task() -> None:
    client = TestClient(app)
    response = client.post(
        "/task/create",
        json={"title": "Implement parser", "description": "Build AST", "priority": 2, "estimated_minutes": 45},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["task_id"] > 0


def test_block_and_pending() -> None:
    client = TestClient(app)
    create = client.post("/task/create", json={"title": "API integration"})
    task_id = create.json()["task_id"]

    blocked = client.post(
        "/task/block",
        json={"task_id": task_id, "reason": "Waiting API key", "dependency": "after 10m"},
    )
    assert blocked.status_code == 200

    pending = client.get("/tasks/pending")
    assert pending.status_code == 200
    assert any(t["id"] == task_id and t["status"] == "blocked" for t in pending.json())


def test_complete_task() -> None:
    client = TestClient(app)
    create = client.post("/task/create", json={"title": "Write tests"})
    task_id = create.json()["task_id"]

    complete = client.post("/task/complete", json={"task_id": task_id})
    assert complete.status_code == 200

    with daemon.session_factory() as session:
        task = session.get(Task, task_id)
        assert task is not None
        assert task.status == TaskStatus.DONE
        assert isinstance(task.updated_at, datetime)
