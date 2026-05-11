from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

FOCUS_SYSTEM_PROMPT = """You are FOCUS, Talha's personal AI Chief of Staff running on his Linux machine.
You have full context of what he is doing on his computer right now.

Your personality: direct, no-fluff, like a senior engineer who keeps things moving.
Your ONE job: make sure no task falls through the cracks.

You always know:
- What Talha is currently working on (from screen activity)
- What tasks are blocked and why
- How long he's been on each thing
- What he started but never finished

When Talha talks to you:
- Be brief (max 2-3 sentences for chat, detailed for reports)
- If he mentions something that sounds like a new task, ask: \"Want me to track that?\"
- If he says \"I'll do X later\", immediately create a pending task
- Never lecture him - just keep him on track

Current context will be injected before each message as JSON."""


@dataclass(slots=True)
class LLMConfig:
    api_key: str
    model: str = "meta/llama-3.1-70b-instruct"
    base_url: str = "https://integrate.api.nvidia.com/v1"


class LLMBrain:
    def __init__(self, config: LLMConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.client: OpenAI | None = None

        if self.config.api_key:
            self.client = OpenAI(base_url=self.config.base_url, api_key=self.config.api_key)
        else:
            self.logger.warning("NVIDIA NIM API key is missing; LLM features running in fallback mode")

    def _chat_completion(self, user_prompt: str, *, temperature: float, max_tokens: int) -> str:
        if not self.client:
            return "LLM unavailable. Tracking is still active locally."

        response = self.client.chat.completions.create(
            model=self.config.model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": FOCUS_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        )
        return response.choices[0].message.content or ""

    def classify_activity(self, window_title: str, app_name: str, url: str = "") -> tuple[str, str]:
        prompt = (
            "Classify this activity into one category and short task name. "
            "Return strict JSON: {\"task_category\": \"...\", \"task_name\": \"...\"}.\n"
            f"app_name={app_name}\nwindow_title={window_title}\nurl={url}"
        )
        raw = self._chat_completion(prompt, temperature=0.3, max_tokens=500)
        try:
            parsed = json.loads(raw)
            return parsed.get("task_category", "uncategorized"), parsed.get("task_name", "Unknown Task")
        except Exception:
            # Deterministic fallback keeps daemon functional when model output is malformed.
            category = "browsing" if "http" in url else ("coding" if app_name.lower() in {"code", "pycharm"} else "general")
            return category, window_title[:80] or app_name or "Unknown Task"

    def analyze_switch(self, from_context: dict[str, Any], to_context: dict[str, Any]) -> str:
        prompt = (
            "Was this task switch intentional or distraction? "
            "Return one short sentence.\n"
            f"from={json.dumps(from_context)}\n"
            f"to={json.dumps(to_context)}"
        )
        return self._chat_completion(prompt, temperature=0.3, max_tokens=500)

    def generate_eod_report(self, activities: list[dict[str, Any]], tasks: list[dict[str, Any]]) -> str:
        prompt = (
            "Generate a structured markdown EOD productivity report with sections:\n"
            "- Time Summary\n- Completed Tasks\n- Still Pending\n- Abandoned/Forgotten Tasks\n"
            "- Tomorrow Priorities\n- Focus Score (0-100)\n"
            f"activities={json.dumps(activities)}\n"
            f"tasks={json.dumps(tasks)}"
        )
        return self._chat_completion(prompt, temperature=0.5, max_tokens=2000)

    def chat(self, message: str, context: dict[str, Any]) -> str:
        contextual_message = f"context={json.dumps(context)}\nmessage={message}"
        return self._chat_completion(contextual_message, temperature=0.7, max_tokens=300)

    def detect_pending_task_resurfacing(self, current_activity: dict[str, Any], pending_tasks: list[dict[str, Any]]) -> str:
        prompt = (
            "Should FOCUS remind Talha about a pending/blocked task now? "
            "Return strict JSON: {\"should_remind\": true/false, \"reason\": \"...\"}.\n"
            f"current_activity={json.dumps(current_activity)}\n"
            f"pending_tasks={json.dumps(pending_tasks)}"
        )
        return self._chat_completion(prompt, temperature=0.3, max_tokens=500)
