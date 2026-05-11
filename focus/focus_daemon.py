from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Optional

import httpx
import uvicorn
import yaml
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, sessionmaker

from db.models import ActivityLog, Conversation, Task, TaskStatus, TaskSwitch, init_db
from llm_brain import FOCUS_SYSTEM_PROMPT, LLMBrain, LLMConfig
from report_generator import ReportGenerator
from resurfacing import ResurfacingEngine
from voice_interface import VoiceInterface

APP_HOST = "127.0.0.1"
APP_PORT = 7799
AW_BASE_URL = "http://127.0.0.1:5600"
POLL_SECONDS = 30


def load_config() -> dict[str, Any]:
    cfg_path = Path.home() / ".focus" / "config.yaml"
    if not cfg_path.exists():
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        cfg_path.write_text(
            yaml.safe_dump(
                {
                    "nvidia_nim_api_key": "",
                    "model": "meta/llama-3.1-70b-instruct",
                    "aw_base_url": AW_BASE_URL,
                    "poll_seconds": POLL_SECONDS,
                },
                sort_keys=False,
            ),
            encoding="utf-8",
        )
    with cfg_path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def setup_logging() -> logging.Logger:
    log_dir = Path.home() / ".focus" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("focus")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger

    handler = TimedRotatingFileHandler(
        filename=str(log_dir / "focus.log"),
        when="midnight",
        backupCount=14,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    logger.addHandler(stream_handler)
    return logger


class TaskCreateRequest(BaseModel):
    title: str = Field(min_length=2, max_length=255)
    description: str = ""
    priority: int = Field(default=3, ge=1, le=5)
    estimated_minutes: int = Field(default=25, ge=1, le=600)


class TaskBlockRequest(BaseModel):
    task_id: int
    reason: str = Field(min_length=2)
    dependency: str = Field(min_length=2)


class TaskCompleteRequest(BaseModel):
    task_id: int


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)


class BrowserContextRequest(BaseModel):
    url: str = ""
    title: str = ""
    selected_text: str = ""
    page_summary: str = ""


class FocusDaemon:
    def __init__(self) -> None:
        self.config = load_config()
        self.logger = setup_logging()
        self.session_factory: sessionmaker[Session] = init_db()
        self.latest_browser_context: dict[str, str] = {}
        self.latest_activity: dict[str, Any] = {}
        self.scheduler = AsyncIOScheduler(timezone="UTC")

        llm_cfg = LLMConfig(
            api_key=self.config.get("nvidia_nim_api_key", ""),
            model=self.config.get("model", "meta/llama-3.1-70b-instruct"),
        )
        self.llm = LLMBrain(config=llm_cfg, logger=self.logger)
        self.report_generator = ReportGenerator(self.llm, self.logger)
        self.resurfacing_engine = ResurfacingEngine(self.logger)
        self.voice: VoiceInterface | None = None
        self.last_classified_task_name: str = ""

        self.app = FastAPI(title="FOCUS Daemon", version="1.0.0")
        self._register_routes()
        self._register_scheduler_jobs()

    def _register_scheduler_jobs(self) -> None:
        poll_seconds = int(self.config.get("poll_seconds", POLL_SECONDS))
        self.scheduler.add_job(self.poll_activitywatch, "interval", seconds=poll_seconds, id="poll_aw")
        self.scheduler.add_job(self.run_resurfacing, "interval", minutes=5, id="resurfacing")
        self.scheduler.add_job(self.generate_eod_report, "cron", hour=18, minute=0, id="eod_report")

    def _register_routes(self) -> None:
        @self.app.on_event("startup")
        async def on_startup() -> None:
            self.scheduler.start()
            voice_cfg = self.config.get("voice", {})
            if voice_cfg.get("enabled", False):
                self.voice = VoiceInterface(
                    whisper_model=voice_cfg.get("whisper_model", "base"),
                    piper_voice_path=voice_cfg.get("piper_voice_path") or None,
                )
                self.voice.start()
            self.logger.info("FOCUS daemon started")

        @self.app.on_event("shutdown")
        async def on_shutdown() -> None:
            if self.voice:
                self.voice.stop()
            self.scheduler.shutdown(wait=False)
            self.logger.info("FOCUS daemon stopped")

        @self.app.post("/task/create")
        async def task_create(payload: TaskCreateRequest) -> dict[str, Any]:
            now = datetime.now(timezone.utc)
            with self.session_factory() as session:
                task = Task(
                    title=payload.title.strip(),
                    description=payload.description.strip(),
                    status=TaskStatus.ACTIVE,
                    created_at=now,
                    updated_at=now,
                    priority=payload.priority,
                    estimated_minutes=payload.estimated_minutes,
                    context_snapshot=json.dumps(self.latest_activity),
                )
                session.add(task)
                session.commit()
                session.refresh(task)
            return {"ok": True, "task_id": task.id}

        @self.app.post("/task/block")
        async def task_block(payload: TaskBlockRequest) -> dict[str, Any]:
            with self.session_factory() as session:
                task = session.get(Task, payload.task_id)
                if not task:
                    raise HTTPException(status_code=404, detail="Task not found")
                task.status = TaskStatus.BLOCKED
                task.blocked_reason = payload.reason.strip()
                task.unblock_condition = payload.dependency.strip()
                task.updated_at = datetime.now(timezone.utc)
                session.commit()
            return {"ok": True}

        @self.app.post("/task/complete")
        async def task_complete(payload: TaskCompleteRequest) -> dict[str, Any]:
            with self.session_factory() as session:
                task = session.get(Task, payload.task_id)
                if not task:
                    raise HTTPException(status_code=404, detail="Task not found")
                task.status = TaskStatus.DONE
                task.updated_at = datetime.now(timezone.utc)
                session.commit()
            return {"ok": True}

        @self.app.get("/tasks/pending")
        async def tasks_pending() -> list[dict[str, Any]]:
            with self.session_factory() as session:
                tasks = session.scalars(
                    select(Task).where(Task.status.in_([TaskStatus.ACTIVE, TaskStatus.BLOCKED])).order_by(Task.priority.asc(), Task.updated_at.desc())
                ).all()
            return [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status.value,
                    "blocked_reason": t.blocked_reason,
                    "unblock_condition": t.unblock_condition,
                    "updated_at": t.updated_at.isoformat(),
                }
                for t in tasks
            ]

        @self.app.get("/tasks/active")
        async def tasks_active() -> dict[str, Any]:
            return {
                "activity": self.latest_activity,
                "browser_context": self.latest_browser_context,
            }

        @self.app.post("/chat")
        async def chat(payload: ChatRequest) -> dict[str, Any]:
            context = self._collect_chat_context()
            with self.session_factory() as session:
                session.add(Conversation(role="user", content=payload.message.strip(), timestamp=datetime.now(timezone.utc)))
                session.commit()

            response = self.llm.chat(payload.message, context=context)

            with self.session_factory() as session:
                session.add(Conversation(role="assistant", content=response, timestamp=datetime.now(timezone.utc)))
                session.commit()
            return {"reply": response}

        @self.app.get("/report/today")
        async def report_today() -> dict[str, Any]:
            markdown = self.generate_eod_report()
            return {"report_markdown": markdown}

        @self.app.post("/context/browser")
        async def context_browser(payload: BrowserContextRequest) -> dict[str, Any]:
            self.latest_browser_context = payload.model_dump()
            return {"ok": True}

    def _collect_chat_context(self) -> dict[str, Any]:
        with self.session_factory() as session:
            pending = session.scalars(
                select(Task).where(Task.status.in_([TaskStatus.ACTIVE, TaskStatus.BLOCKED])).order_by(Task.updated_at.desc())
            ).all()
            recent_activity = session.scalars(
                select(ActivityLog)
                .where(ActivityLog.timestamp >= datetime.now(timezone.utc) - timedelta(hours=2))
                .order_by(ActivityLog.timestamp.desc())
                .limit(200)
            ).all()

        return {
            "system_prompt": FOCUS_SYSTEM_PROMPT,
            "current_activity": self.latest_activity,
            "browser_context": self.latest_browser_context,
            "pending_tasks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status.value,
                    "blocked_reason": t.blocked_reason,
                    "unblock_condition": t.unblock_condition,
                    "updated_at": t.updated_at.isoformat(),
                }
                for t in pending
            ],
            "recent_activity": [
                {
                    "timestamp": a.timestamp.isoformat(),
                    "app_name": a.app_name,
                    "window_title": a.window_title,
                    "url": a.url,
                    "duration_seconds": a.duration_seconds,
                    "category": a.category,
                }
                for a in recent_activity
            ],
        }

    def generate_eod_report(self) -> str:
        today = date.today().isoformat()
        with self.session_factory() as session:
            start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
            activities = session.scalars(select(ActivityLog).where(ActivityLog.timestamp >= start)).all()
            tasks = session.scalars(select(Task)).all()

            report_md = self.report_generator.generate(today=today, activities=activities, tasks=tasks)
            self.report_generator.persist(session=session, report_date=today, report_markdown=report_md)
            session.commit()
            return report_md

    def run_resurfacing(self) -> None:
        with self.session_factory() as session:
            pending = session.scalars(select(Task).where(Task.status.in_([TaskStatus.ACTIVE, TaskStatus.BLOCKED]))).all()
            if not pending:
                return
            suggestions = self.resurfacing_engine.check(
                current_activity=self.latest_activity,
                tasks=pending,
            )
            for msg in suggestions:
                self.logger.info("RESURFACING: %s", msg)

    def poll_activitywatch(self) -> None:
        aw_base = self.config.get("aw_base_url", AW_BASE_URL)
        now = datetime.now(timezone.utc)
        start = now - timedelta(seconds=int(self.config.get("poll_seconds", POLL_SECONDS)) + 5)

        query = {
            "timeperiods": [f"{start.isoformat()}/{now.isoformat()}"],
            "query": [
                "events = query_bucket(find_bucket('aw-watcher-window_')); RETURN = events;",
                "events = query_bucket(find_bucket('aw-watcher-afk_')); RETURN = events;",
            ],
        }

        try:
            with httpx.Client(timeout=8.0) as client:
                response = client.post(f"{aw_base}/api/0/query/", json=query)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:
            self.logger.warning("ActivityWatch poll failed: %s", exc)
            return

        window_events = payload[0] if isinstance(payload, list) and payload else []
        afk_events = payload[1] if isinstance(payload, list) and len(payload) > 1 else []
        if not window_events:
            return

        last = window_events[-1]
        data = last.get("data", {})
        app_name = data.get("app", "")
        window_title = data.get("title", "")
        duration_seconds = int(float(last.get("duration", 0)))
        url = self.latest_browser_context.get("url", "")
        is_afk = bool(afk_events[-1].get("data", {}).get("status") == "afk") if afk_events else False

        category, task_name = self.llm.classify_activity(window_title=window_title, app_name=app_name, url=url)
        self.latest_activity = {
            "timestamp": now.isoformat(),
            "app_name": app_name,
            "window_title": window_title,
            "url": url,
            "duration_seconds": duration_seconds,
            "category": category,
            "afk": is_afk,
        }

        with self.session_factory() as session:
            entry = ActivityLog(
                timestamp=now,
                app_name=app_name,
                window_title=window_title,
                url=url,
                duration_seconds=duration_seconds,
                category=category,
            )
            session.add(entry)

            if self.last_classified_task_name and self.last_classified_task_name != task_name:
                from_task = session.scalar(
                    select(Task).where(and_(Task.title == self.last_classified_task_name, Task.status != TaskStatus.DONE))
                )
                to_task = session.scalar(
                    select(Task).where(and_(Task.title == task_name, Task.status != TaskStatus.DONE))
                )
                switch_reason = self.llm.analyze_switch(
                    from_context={"task": self.last_classified_task_name},
                    to_context={"task": task_name, "activity": self.latest_activity},
                )
                session.add(
                    TaskSwitch(
                        from_task_id=from_task.id if from_task else None,
                        to_task_id=to_task.id if to_task else None,
                        switch_reason=switch_reason,
                        timestamp=now,
                    )
                )

                if from_task and from_task.status == TaskStatus.ACTIVE:
                    from_task.updated_at = now

            self.last_classified_task_name = task_name
            session.commit()


daemon = FocusDaemon()
app = daemon.app


if __name__ == "__main__":
    uvicorn.run("focus_daemon:app", host=APP_HOST, port=APP_PORT, reload=False)
