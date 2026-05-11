from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from db.models import Task, TaskStatus


class ResurfacingEngine:
    def __init__(self, logger: logging.Logger) -> None:
        self.logger = logger

    def _minutes_since(self, dt: datetime) -> float:
        now = datetime.now(timezone.utc)
        updated = dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        return (now - updated).total_seconds() / 60.0

    def _condition_met(self, task: Task, activity_text: str, idle_minutes: float) -> bool:
        cond = (task.unblock_condition or "").strip().lower()
        if not cond:
            return False

        if cond.startswith("after ") and cond.endswith("m"):
            raw = cond.removeprefix("after ").removesuffix("m").strip()
            if raw.isdigit():
                return idle_minutes >= int(raw)

        keywords = [k.strip() for k in cond.split("|") if k.strip()]
        return any(k in activity_text for k in keywords)

    def check(self, current_activity: dict[str, Any], tasks: list[Task]) -> list[str]:
        suggestions: list[str] = []
        activity_blob = json.dumps(current_activity).lower()

        for task in tasks:
            minutes_since_update = self._minutes_since(task.updated_at)
            if task.status == TaskStatus.BLOCKED:
                if self._condition_met(task, activity_blob, minutes_since_update):
                    suggestions.append(
                        f"Remember '{task.title}'. You were blocked on '{task.blocked_reason}'. Can we resume now?"
                    )
            if task.status == TaskStatus.ACTIVE and minutes_since_update >= 45:
                suggestions.append(
                    f"You switched from '{task.title}' about {int(minutes_since_update)} minutes ago. Is it completed or should we re-plan?"
                )

        return suggestions
