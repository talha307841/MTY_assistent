from __future__ import annotations

import logging

from llm_brain import LLMBrain, LLMConfig


def test_classify_activity_fallback() -> None:
    logger = logging.getLogger("test-llm")
    brain = LLMBrain(LLMConfig(api_key=""), logger=logger)

    category, task_name = brain.classify_activity(
        window_title="Editing focus_daemon.py",
        app_name="Code",
        url="",
    )

    assert category in {"coding", "general", "uncategorized", "browsing"}
    assert isinstance(task_name, str)


def test_chat_fallback() -> None:
    logger = logging.getLogger("test-llm")
    brain = LLMBrain(LLMConfig(api_key=""), logger=logger)
    response = brain.chat("What should I do?", context={"pending_tasks": []})
    assert "LLM unavailable" in response
