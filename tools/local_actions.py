"""Safe local actions exposed to EDITH's tool-calling model.

These tools deliberately avoid arbitrary shell execution. They support common
voice tasks while keeping writes inside standard personal folders.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from tools.registry import registry


ALLOWED_ROOTS = tuple((Path.home() / name).resolve() for name in ("Desktop", "Documents", "Downloads"))
APP_ALIASES = {
    "notepad": ["notepad.exe"],
    "calculator": ["calc.exe"],
    "explorer": ["explorer.exe"],
    "settings": ["ms-settings:"],
    "task manager": ["taskmgr.exe"],
}


def _allowed_path(path: str) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.home() / "Documents" / candidate
    candidate = candidate.resolve()
    if not any(candidate == root or root in candidate.parents for root in ALLOWED_ROOTS):
        raise ValueError("EDITH may only modify files in Desktop, Documents, or Downloads.")
    return candidate


@registry.register(
    name="open_local_path",
    description="Open a local file or folder in its default Windows application.",
    parameters={"path": {"type": "string", "description": "Path of the local file or folder to open."}},
    required=["path"],
)
def open_local_path(path: str) -> str:
    target = Path(path).expanduser()
    if not target.exists():
        return f"Error: '{target}' does not exist."
    try:
        os.startfile(str(target))
        return f"Opened {target}"
    except OSError as exc:
        return f"Error opening '{target}': {exc}"


@registry.register(
    name="launch_app",
    description="Launch a built-in Windows app. Supported: Notepad, Calculator, Explorer, Settings, Task Manager. Never use this for arbitrary commands.",
    parameters={"app": {"type": "string", "description": "One supported app name."}},
    required=["app"],
)
def launch_app(app: str) -> str:
    key = app.strip().lower()
    command = APP_ALIASES.get(key)
    if command is None:
        return f"Unsupported app '{app}'. Supported apps: {', '.join(APP_ALIASES)}."
    try:
        if command[0] == "ms-settings:":
            os.startfile(command[0])
        else:
            subprocess.Popen(command, close_fds=True)
        return f"Launched {key}."
    except OSError as exc:
        return f"Error launching {key}: {exc}"


@registry.register(
    name="create_text_file",
    description="Create a new plain-text file in Desktop, Documents, or Downloads. It will not overwrite an existing file.",
    parameters={
        "path": {"type": "string", "description": "File path; relative paths are inside Documents."},
        "content": {"type": "string", "description": "Full text to save."},
    },
    required=["path", "content"],
)
def create_text_file(path: str, content: str) -> str:
    try:
        target = _allowed_path(path)
        if target.suffix.lower() not in {".txt", ".md", ".csv", ".json", ".py"}:
            return "Error: EDITH can only create text-based files (.txt, .md, .csv, .json, .py)."
        if target.exists():
            return f"Error: '{target}' already exists. EDITH will not overwrite files."
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Saved {len(content)} characters to {target}"
    except (OSError, ValueError) as exc:
        return f"Error saving file: {exc}"


@registry.register(
    name="append_text_file",
    description="Append text to an existing file in Desktop, Documents, or Downloads. This changes a local file.",
    parameters={
        "path": {"type": "string", "description": "Path of the existing text file."},
        "content": {"type": "string", "description": "Text to add."},
    },
    required=["path", "content"],
)
def append_text_file(path: str, content: str) -> str:
    try:
        target = _allowed_path(path)
        if not target.exists() or not target.is_file():
            return f"Error: '{target}' is not an existing file."
        with target.open("a", encoding="utf-8") as file:
            file.write(content)
        return f"Appended {len(content)} characters to {target}"
    except (OSError, ValueError) as exc:
        return f"Error updating file: {exc}"
