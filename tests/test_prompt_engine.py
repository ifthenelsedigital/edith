from unittest import TestCase

from core.prompt_engine import build_messages


class TestCompactPrompt(TestCase):
    def test_compact_prompt_keeps_memory_and_reduces_system_prompt(self):
        regular = build_messages("Hi", [], "The user prefers short replies.")
        compact = build_messages("Hi", [], "The user prefers short replies.", compact=True)

        self.assertLess(len(compact[0]["content"]), len(regular[0]["content"]))
        self.assertIn("The user prefers short replies.", compact[0]["content"])
        self.assertIn("Never claim to perform a computer action", compact[0]["content"])
