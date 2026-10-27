"""
EDITH Tools — Windows Control

System volume and screen brightness control using pycaw and screen-brightness-control.
"""

from __future__ import annotations

import logging
import platform

from tools.registry import registry

logger = logging.getLogger("edith.tools.windows")


# ════════════════════════════════════════════════
#  Volume Control (pycaw)
# ════════════════════════════════════════════════

def _get_volume_interface():
    """Get the Windows Core Audio volume interface."""
    from ctypes import cast, POINTER
    from comtypes import CLSCTX_ALL
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume

    devices = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return cast(interface, POINTER(IAudioEndpointVolume))


@registry.register(
    name="set_volume",
    description="Set the system audio volume to a specific level (0-100). Use this when the user asks to change, increase, decrease, or set the volume.",
    parameters={
        "level": {
            "type": "integer",
            "description": "Volume level from 0 (mute) to 100 (maximum)",
        }
    },
    required=["level"],
)
def set_volume(level: int) -> str:
    """Set system volume to a percentage (0-100)."""
    if platform.system() != "Windows":
        return "Error: Volume control is only available on Windows."

    level = max(0, min(100, int(level)))
    try:
        volume = _get_volume_interface()
        volume.SetMasterVolumeLevelScalar(level / 100.0, None)
        return f"Volume set to {level}%"
    except Exception as e:
        return f"Error setting volume: {e}"


@registry.register(
    name="get_volume",
    description="Get the current system audio volume level as a percentage (0-100). Use this when the user asks what the current volume is.",
    parameters={},
    required=[],
)
def get_volume() -> str:
    """Get current system volume as a percentage."""
    if platform.system() != "Windows":
        return "Error: Volume control is only available on Windows."

    try:
        volume = _get_volume_interface()
        current = volume.GetMasterVolumeLevelScalar()
        level = round(current * 100)
        return f"Current volume: {level}%"
    except Exception as e:
        return f"Error getting volume: {e}"


# ════════════════════════════════════════════════
#  Brightness Control (screen-brightness-control)
# ════════════════════════════════════════════════

@registry.register(
    name="set_brightness",
    description="Set the screen brightness to a specific level (0-100). Use this when the user asks to change, increase, decrease, or set brightness.",
    parameters={
        "level": {
            "type": "integer",
            "description": "Brightness level from 0 (darkest) to 100 (brightest)",
        }
    },
    required=["level"],
)
def set_brightness(level: int) -> str:
    """Set screen brightness to a percentage (0-100)."""
    try:
        import screen_brightness_control as sbc

        level = max(0, min(100, int(level)))
        sbc.set_brightness(level)
        return f"Screen brightness set to {level}%"
    except Exception as e:
        return f"Error setting brightness: {e}"


@registry.register(
    name="get_brightness",
    description="Get the current screen brightness level as a percentage (0-100). Use this when the user asks what the current brightness is.",
    parameters={},
    required=[],
)
def get_brightness() -> str:
    """Get current screen brightness."""
    try:
        import screen_brightness_control as sbc

        brightness = sbc.get_brightness()
        if isinstance(brightness, list):
            brightness = brightness[0]
        return f"Current brightness: {brightness}%"
    except Exception as e:
        return f"Error getting brightness: {e}"
