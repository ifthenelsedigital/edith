"""
EDITH API — WebSocket Endpoint

Real-time bidirectional communication for the chat interface.
Supports the approval flow for the deterministic command router.
"""

from __future__ import annotations

import json
import logging
import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.orchestrator import (
    process_message_stream,
    execute_approved_action,
    execute_denied_action,
)

logger = logging.getLogger("edith.api.websocket")
router = APIRouter()


class ConnectionManager:
    """Manages active WebSocket connections."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"Client connected ({len(self.active_connections)} active)")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
        logger.info(f"Client disconnected ({len(self.active_connections)} active)")

    async def send_json(self, websocket: WebSocket, data: dict) -> bool:
        """Send JSON to a specific client. Returns True if sent successfully, False otherwise."""
        try:
            await websocket.send_json(data)
            return True
        except Exception as e:
            logger.debug(f"Failed to send message over websocket (client likely disconnected): {e}")
            return False


manager = ConnectionManager()


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket):
    """
    Main chat WebSocket endpoint.

    Client sends:
        {"type": "message", "content": "...", "session_id": "..." (optional)}
        {"type": "approval_response", "approval_id": "...", "approved": true/false}

    Server sends:
        {"type": "session", "session_id": "..."}
        {"type": "session_title", "title": "..."}
        {"type": "tool_start", "name": "...", "args": {...}}
        {"type": "tool_result", "name": "...", "result": "..."}
        {"type": "pending_approval", "approval_id": "...", "tool_name": "...", "args": {...}, "description": "..."}
        {"type": "token", "content": "..."}
        {"type": "done", "full_response": "..."}
        {"type": "error", "message": "..."}
    """
    await manager.connect(websocket)

    try:
        while True:
            # Wait for client message
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await manager.send_json(websocket, {
                    "type": "error",
                    "message": "Invalid JSON",
                })
                continue

            msg_type = data.get("type", "")

            if msg_type == "message":
                content = data.get("content", "").strip()
                session_id = data.get("session_id")

                if not content:
                    await manager.send_json(websocket, {
                        "type": "error",
                        "message": "Empty message",
                    })
                    continue

                # Process through the orchestrator with streaming
                try:
                    client_connected = True
                    async for event in process_message_stream(content, session_id):
                        if client_connected:
                            client_connected = await manager.send_json(websocket, event)
                        # Small delay between tokens for a natural streaming feel
                        if client_connected and event.get("type") == "token":
                            await asyncio.sleep(0.02)
                except Exception as e:
                    logger.error(f"Orchestrator error: {e}", exc_info=True)
                    await manager.send_json(websocket, {
                        "type": "error",
                        "message": f"Processing error: {str(e)}",
                    })

            elif msg_type == "approval_response":
                approval_id = data.get("approval_id", "")
                approved = data.get("approved", False)

                if not approval_id:
                    await manager.send_json(websocket, {
                        "type": "error",
                        "message": "Missing approval_id",
                    })
                    continue

                try:
                    client_connected = True
                    if approved:
                        async for event in execute_approved_action(approval_id):
                            if client_connected:
                                client_connected = await manager.send_json(websocket, event)
                            if client_connected and event.get("type") == "token":
                                await asyncio.sleep(0.02)
                    else:
                        async for event in execute_denied_action(approval_id):
                            if client_connected:
                                client_connected = await manager.send_json(websocket, event)
                            if client_connected and event.get("type") == "token":
                                await asyncio.sleep(0.02)
                except Exception as e:
                    logger.error(f"Approval execution error: {e}", exc_info=True)
                    await manager.send_json(websocket, {
                        "type": "error",
                        "message": f"Execution error: {str(e)}",
                    })


            elif msg_type == "ping":
                await manager.send_json(websocket, {"type": "pong"})

            else:
                await manager.send_json(websocket, {
                    "type": "error",
                    "message": f"Unknown message type: {msg_type}",
                })

    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}", exc_info=True)
        manager.disconnect(websocket)
