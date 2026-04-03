import os
import sys
from pathlib import Path

APP_NAME = "TriedingView"
USER_DATA_DIR_ENV = "TRIEDINGVIEW_USER_DATA_DIR"


def get_bundle_root() -> Path:
    """Return the read-only app root for source runs and PyInstaller bundles."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS).resolve()
    return Path(__file__).resolve().parents[1]


def get_resource_path(*parts: str) -> str:
    return str(get_bundle_root().joinpath(*parts))


def get_user_data_dir() -> Path:
    """Return the writable per-user app data directory."""
    override = os.environ.get(USER_DATA_DIR_ENV)
    if override:
        data_dir = Path(override).expanduser()
    elif sys.platform == "darwin":
        data_dir = Path.home() / "Library" / "Application Support" / APP_NAME
    elif sys.platform == "win32":
        data_dir = Path(
            os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")
        ) / APP_NAME
    else:
        data_dir = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_user_data_path(*parts: str) -> str:
    return str(get_user_data_dir().joinpath(*parts))
