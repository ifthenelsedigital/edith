from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from core import orchestrator


class TestResolveSession(IsolatedAsyncioTestCase):
    async def test_reuses_existing_session(self):
        with (
            patch.object(orchestrator, "get_session", new=AsyncMock(return_value={"id": "existing"})),
            patch.object(orchestrator, "create_session", new=AsyncMock()) as create_session,
        ):
            session_id, is_new = await orchestrator._resolve_session("existing")

        self.assertEqual(session_id, "existing")
        self.assertFalse(is_new)
        create_session.assert_not_awaited()

    async def test_replaces_missing_session(self):
        with (
            patch.object(orchestrator, "get_session", new=AsyncMock(return_value=None)),
            patch.object(orchestrator, "create_session", new=AsyncMock(return_value="replacement")),
        ):
            session_id, is_new = await orchestrator._resolve_session("deleted")

        self.assertEqual(session_id, "replacement")
        self.assertTrue(is_new)

    async def test_creates_session_when_none_is_provided(self):
        with patch.object(
            orchestrator,
            "create_session",
            new=AsyncMock(return_value="new"),
        ):
            session_id, is_new = await orchestrator._resolve_session(None)

        self.assertEqual(session_id, "new")
        self.assertTrue(is_new)
