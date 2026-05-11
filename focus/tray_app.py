from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import httpx
from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QInputDialog,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
)

DAEMON_URL = "http://127.0.0.1:7799"


def make_circle_icon(color: QColor) -> QIcon:
    pixmap = QPixmap(32, 32)
    pixmap.fill(QColor(0, 0, 0, 0))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(color)
    painter.setPen(QColor("#2f2f2f"))
    painter.drawEllipse(4, 4, 24, 24)
    painter.end()
    return QIcon(pixmap)


class FocusTray:
    def __init__(self) -> None:
        self.app = QApplication(sys.argv)
        self.tray = QSystemTrayIcon()

        assets = Path(__file__).resolve().parent / "assets"
        self.icon_green = QIcon(str(assets / "tray_green.svg")) if (assets / "tray_green.svg").exists() else make_circle_icon(QColor("#27ae60"))
        self.icon_yellow = QIcon(str(assets / "tray_yellow.svg")) if (assets / "tray_yellow.svg").exists() else make_circle_icon(QColor("#f1c40f"))
        self.icon_red = QIcon(str(assets / "tray_red.svg")) if (assets / "tray_red.svg").exists() else make_circle_icon(QColor("#e74c3c"))

        self.tray.setIcon(self.icon_green)
        self.menu = QMenu()
        self._build_menu()
        self.tray.setContextMenu(self.menu)
        self.tray.show()

        self.timer = QTimer()
        self.timer.timeout.connect(self.refresh_state)
        self.timer.start(30_000)
        self.refresh_state()

    def _build_menu(self) -> None:
        what_action = QAction("What am I doing?", self.menu)
        what_action.triggered.connect(self.show_current)
        self.menu.addAction(what_action)

        blocked_action = QAction("I'm blocked on...", self.menu)
        blocked_action.triggered.connect(self.mark_blocked)
        self.menu.addAction(blocked_action)

        switch_action = QAction("Switch task", self.menu)
        switch_action.triggered.connect(self.switch_task)
        self.menu.addAction(switch_action)

        pending_action = QAction("What's pending?", self.menu)
        pending_action.triggered.connect(self.show_pending)
        self.menu.addAction(pending_action)

        report_action = QAction("End of Day Report", self.menu)
        report_action.triggered.connect(self.eod_report)
        self.menu.addAction(report_action)

        quit_action = QAction("Quit", self.menu)
        quit_action.triggered.connect(self.app.quit)
        self.menu.addAction(quit_action)

    def _request(self, method: str, endpoint: str, payload: dict[str, Any] | None = None) -> Any:
        with httpx.Client(timeout=8.0) as client:
            res = client.request(method, f"{DAEMON_URL}{endpoint}", json=payload)
            res.raise_for_status()
            return res.json()

    def refresh_state(self) -> None:
        try:
            pending = self._request("GET", "/tasks/pending")
            active = self._request("GET", "/tasks/active")
        except Exception:
            self.tray.setIcon(self.icon_yellow)
            self.tray.setToolTip("FOCUS daemon unreachable")
            return

        blocked = [t for t in pending if t.get("status") == "blocked"]
        is_switching = active.get("activity", {}).get("duration_seconds", 0) < 45

        if blocked:
            self.tray.setIcon(self.icon_red)
        elif is_switching:
            self.tray.setIcon(self.icon_yellow)
        else:
            self.tray.setIcon(self.icon_green)

        title = active.get("activity", {}).get("window_title", "No active window")
        self.tray.setToolTip(f"FOCUS: {title}")

    def show_current(self) -> None:
        try:
            active = self._request("GET", "/tasks/active")
            activity = active.get("activity", {})
            text = (
                f"App: {activity.get('app_name', 'N/A')}\n"
                f"Window: {activity.get('window_title', 'N/A')}\n"
                f"Category: {activity.get('category', 'N/A')}"
            )
            QMessageBox.information(None, "Current Focus", text)
        except Exception as exc:
            QMessageBox.warning(None, "FOCUS", f"Could not fetch current activity: {exc}")

    def mark_blocked(self) -> None:
        task_id, ok = QInputDialog.getInt(None, "Block Task", "Task ID:", value=1, min=1)
        if not ok:
            return
        reason, ok = QInputDialog.getText(None, "Block Task", "Reason:")
        if not ok or not reason.strip():
            return
        dependency, ok = QInputDialog.getText(None, "Block Task", "Unblock condition/dependency:")
        if not ok or not dependency.strip():
            return
        try:
            self._request(
                "POST",
                "/task/block",
                {"task_id": task_id, "reason": reason.strip(), "dependency": dependency.strip()},
            )
            self.tray.showMessage("FOCUS", "Task marked as blocked")
            self.refresh_state()
        except Exception as exc:
            QMessageBox.warning(None, "FOCUS", f"Could not mark blocked: {exc}")

    def switch_task(self) -> None:
        try:
            pending = self._request("GET", "/tasks/pending")
        except Exception as exc:
            QMessageBox.warning(None, "FOCUS", f"Could not fetch tasks: {exc}")
            return

        if not pending:
            QMessageBox.information(None, "FOCUS", "No pending tasks.")
            return

        formatted = "\n".join(f"#{t['id']} [{t['status']}] {t['title']}" for t in pending)
        QMessageBox.information(None, "Switch Task", formatted)

    def show_pending(self) -> None:
        try:
            pending = self._request("GET", "/tasks/pending")
            if not pending:
                QMessageBox.information(None, "FOCUS", "No pending tasks.")
                return
            formatted = "\n".join(
                f"#{t['id']} [{t['status']}] {t['title']} (blocker: {t.get('blocked_reason', '')})" for t in pending
            )
            QMessageBox.information(None, "Pending Tasks", formatted)
        except Exception as exc:
            QMessageBox.warning(None, "FOCUS", f"Could not fetch pending tasks: {exc}")

    def eod_report(self) -> None:
        try:
            report = self._request("GET", "/report/today")
            text = report.get("report_markdown", "No report generated")
            QMessageBox.information(None, "EOD Report", text[:3500])
        except Exception as exc:
            QMessageBox.warning(None, "FOCUS", f"Could not generate report: {exc}")

    def run(self) -> int:
        return self.app.exec()


if __name__ == "__main__":
    tray = FocusTray()
    raise SystemExit(tray.run())
