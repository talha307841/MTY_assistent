from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from db.models import ActivityLog, DailyReport, Task
from llm_brain import LLMBrain


class ReportGenerator:
    def __init__(self, llm: LLMBrain, logger) -> None:
        self.llm = llm
        self.logger = logger

    def _serialize_activities(self, activities: list[ActivityLog]) -> list[dict[str, Any]]:
        return [
            {
                "timestamp": a.timestamp.isoformat(),
                "app_name": a.app_name,
                "window_title": a.window_title,
                "url": a.url,
                "duration_seconds": a.duration_seconds,
                "category": a.category,
            }
            for a in activities
        ]

    def _serialize_tasks(self, tasks: list[Task]) -> list[dict[str, Any]]:
        return [
            {
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "status": t.status.value,
                "blocked_reason": t.blocked_reason,
                "unblock_condition": t.unblock_condition,
                "priority": t.priority,
                "estimated_minutes": t.estimated_minutes,
                "updated_at": t.updated_at.isoformat(),
            }
            for t in tasks
        ]

    def generate(self, today: str, activities: list[ActivityLog], tasks: list[Task]) -> str:
        try:
            report = self.llm.generate_eod_report(
                activities=self._serialize_activities(activities),
                tasks=self._serialize_tasks(tasks),
            )
            if report.strip():
                return report
        except Exception as exc:
            self.logger.warning("LLM report generation failed: %s", exc)

        # Fallback report keeps the system useful when NIM is down.
        categories: dict[str, int] = {}
        for a in activities:
            categories[a.category] = categories.get(a.category, 0) + a.duration_seconds

        done = [t for t in tasks if t.status.value == "done"]
        blocked = [t for t in tasks if t.status.value == "blocked"]
        active = [t for t in tasks if t.status.value == "active"]

        lines = [
            f"# FOCUS EOD Report - {today}",
            "",
            "## Time Summary",
        ]
        for cat, sec in sorted(categories.items(), key=lambda x: x[1], reverse=True):
            lines.append(f"- {cat}: {round(sec / 60, 1)} minutes")

        lines.append("\n## Completed Tasks")
        lines.extend([f"- {t.title}" for t in done] or ["- None"])

        lines.append("\n## Still Pending")
        lines.extend([f"- {t.title}" for t in active] or ["- None"])

        lines.append("\n## Blocked")
        lines.extend([f"- {t.title} (reason: {t.blocked_reason})" for t in blocked] or ["- None"])

        lines.append("\n## Focus Score")
        focus_score = max(0, 100 - (len(blocked) * 8 + max(0, len(active) - len(done)) * 3))
        lines.append(f"- {focus_score}/100")
        return "\n".join(lines)

    def persist(self, session, report_date: str, report_markdown: str) -> DailyReport:
        existing = session.query(DailyReport).filter(DailyReport.date == report_date).first()
        if existing:
            existing.report_markdown = report_markdown
            existing.generated_at = datetime.now(UTC)
            report = existing
        else:
            report = DailyReport(date=report_date, report_markdown=report_markdown, generated_at=datetime.now(UTC))
            session.add(report)

        out_dir = Path.home() / ".focus" / "reports"
        out_dir.mkdir(parents=True, exist_ok=True)
        html = self._markdown_to_html(report_markdown)
        (out_dir / f"{report_date}.html").write_text(html, encoding="utf-8")
        return report

    def _markdown_to_html(self, markdown_text: str) -> str:
        escaped = markdown_text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return (
            "<html><head><meta charset='utf-8'><title>FOCUS Report</title></head>"
            "<body style='font-family: sans-serif; max-width: 900px; margin: 2rem auto;'>"
            f"<pre style='white-space: pre-wrap'>{escaped}</pre>"
            "</body></html>"
        )
