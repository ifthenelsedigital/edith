"""
EDITH Tools — Browser Control

Tab management via Selenium 4 WebDriver.
The browser launches lazily (only when a browser tool is first used).
"""

from __future__ import annotations

import logging
from typing import Optional

from tools.registry import registry
from config import get_settings

logger = logging.getLogger("edith.tools.browser")

# ── Lazy browser instance ──
_driver = None


def _get_driver():
    """Lazily initialize the Selenium WebDriver."""
    global _driver
    if _driver is not None:
        try:
            # Test if driver is still alive
            _ = _driver.title
            return _driver
        except Exception:
            _driver = None

    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.chrome.service import Service

    settings = get_settings()

    options = Options()
    if settings.browser_headless:
        options.add_argument("--headless=new")

    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    # Keep the browser open even if the script exits
    options.add_experimental_option("detach", True)

    try:
        _driver = webdriver.Chrome(options=options)
        logger.info("Chrome browser launched")
        return _driver
    except Exception as e:
        logger.error(f"Failed to launch Chrome: {e}")
        raise


def cleanup_browser():
    """Close the browser on shutdown."""
    global _driver
    if _driver is not None:
        try:
            _driver.quit()
            logger.info("Browser closed")
        except Exception:
            pass
        _driver = None


# ════════════════════════════════════════════════
#  Browser Tools
# ════════════════════════════════════════════════

@registry.register(
    name="open_url",
    description="Open a URL in the web browser. Opens a new tab if the browser is already open. Use this when the user asks to open a website, go to a URL, or browse something.",
    parameters={
        "url": {
            "type": "string",
            "description": "The full URL to open (e.g., 'https://www.google.com')",
        }
    },
    required=["url"],
)
def open_url(url: str) -> str:
    """Open a URL in Chrome."""
    try:
        # Ensure URL has a scheme
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        driver = _get_driver()

        # If there's already a page loaded, open in new tab
        if driver.current_url != "data:," and driver.current_url != "about:blank":
            driver.switch_to.new_window("tab")

        driver.get(url)
        title = driver.title
        return f"Opened: {title} ({url})"
    except Exception as e:
        return f"Error opening URL: {e}"


@registry.register(
    name="list_tabs",
    description="List all currently open browser tabs with their titles and URLs. Use this when the user asks what tabs are open.",
    parameters={},
    required=[],
)
def list_tabs() -> str:
    """List all open browser tabs."""
    try:
        driver = _get_driver()
        original_handle = driver.current_window_handle
        tabs = []

        for i, handle in enumerate(driver.window_handles):
            driver.switch_to.window(handle)
            tabs.append(f"  [{i}] {driver.title} — {driver.current_url}")

        # Switch back to original tab
        driver.switch_to.window(original_handle)

        if not tabs:
            return "No tabs are open."

        return f"Open tabs ({len(tabs)}):\n" + "\n".join(tabs)
    except Exception as e:
        return f"Error listing tabs: {e}"


@registry.register(
    name="switch_tab",
    description="Switch to a browser tab by its index number. Use list_tabs first to see available tabs.",
    parameters={
        "index": {
            "type": "integer",
            "description": "The tab index number (0-based, as shown by list_tabs)",
        }
    },
    required=["index"],
)
def switch_tab(index: int) -> str:
    """Switch to a tab by index."""
    try:
        driver = _get_driver()
        handles = driver.window_handles

        if index < 0 or index >= len(handles):
            return f"Invalid tab index: {index}. There are {len(handles)} tabs (0-{len(handles)-1})."

        driver.switch_to.window(handles[index])
        return f"Switched to tab [{index}]: {driver.title}"
    except Exception as e:
        return f"Error switching tab: {e}"


@registry.register(
    name="close_tab",
    description="Close a browser tab by its index number. Use list_tabs first to see available tabs.",
    parameters={
        "index": {
            "type": "integer",
            "description": "The tab index number to close (0-based)",
        }
    },
    required=["index"],
)
def close_tab(index: int) -> str:
    """Close a specific tab by index."""
    try:
        driver = _get_driver()
        handles = driver.window_handles

        if index < 0 or index >= len(handles):
            return f"Invalid tab index: {index}. There are {len(handles)} tabs."

        # Switch to the tab to close it
        driver.switch_to.window(handles[index])
        title = driver.title
        driver.close()

        # Switch to remaining tab
        remaining = driver.window_handles
        if remaining:
            driver.switch_to.window(remaining[0])

        return f"Closed tab [{index}]: {title}"
    except Exception as e:
        return f"Error closing tab: {e}"
