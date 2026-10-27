import pytest

from brain.llm_client import LLMClient


def test_sanitize_messages_for_non_tool_model_removes_tool_content():
    client = LLMClient()
    messages = [
        {"role": "system", "content": "You are helpful"},
        {"role": "assistant", "content": "I can help", "tool_calls": [{"function": {"name": "search"}}]},
        {"role": "tool", "content": "tool result", "tool_name": "search"},
        {"role": "user", "content": "Hello"},
    ]

    cleaned = client._sanitize_messages_for_non_tool_model(messages)

    assert cleaned[0]["role"] == "system"
    assert cleaned[1]["role"] == "assistant"
    assert "tool_calls" not in cleaned[1]
    assert all(msg["role"] != "tool" for msg in cleaned)
