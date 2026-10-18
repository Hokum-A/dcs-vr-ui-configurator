import os
import json
import sys
from pathlib import Path

BASE_DIR = (
    Path(sys.executable).resolve().parent
    if getattr(sys, "frozen", False)
    else Path(__file__).resolve().parent
)
SETTINGS_FILE = BASE_DIR / "settings.json"
BACKUPS_DIR = BASE_DIR / "backups"
ORIGINAL_BACKUPS_DIR = BACKUPS_DIR / "original"
HISTORY_BACKUPS_DIR = BACKUPS_DIR / "history"
APP_VERSION = "1.01"

DEFAULT_SETTINGS = {
    "dcs_path": r"C:\Program Files\Eagle Dynamics\DCS World",
    "saved_games_path": str(Path.home() / "Saved Games" / "DCS.openbeta"),
    "active_preset": "recommended_vr",
    "saved_custom_profile": {},
    "window_width": 1380,
    "window_height": 766,
    "language": "ru"
}

def load_settings() -> dict:
    from path_detector import detect_dcs_install_path, detect_saved_games_path
    defaults = DEFAULT_SETTINGS.copy()
    auto_dcs = detect_dcs_install_path()
    if auto_dcs:
        defaults["dcs_path"] = auto_dcs
    auto_sg = detect_saved_games_path()
    if auto_sg:
        defaults["saved_games_path"] = auto_sg

    if not SETTINGS_FILE.exists():
        save_settings(defaults)
        return defaults.copy()
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            merged = defaults.copy()
            merged.update(data)
            # If saved dcs_path doesn't exist, try auto-detection
            if not Path(merged.get("dcs_path", "")).exists() and auto_dcs:
                merged["dcs_path"] = auto_dcs
            return merged
    except Exception:
        return defaults.copy()

def save_settings(settings: dict) -> None:
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=4, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving settings: {e}")

def get_target_files(dcs_path: str, saved_games_path: str) -> dict:
    dcs = Path(dcs_path)
    sg = Path(saved_games_path)
    return {
        "gameMessages_lua": dcs / "Scripts" / "UI" / "gameMessages.lua",
        "gameMessages_dlg": dcs / "Scripts" / "UI" / "gameMessages.dlg",
        "CommandMenu_lua": dcs / "Scripts" / "UI" / "RadioCommandDialogPanel" / "CommandMenu.lua",
        "CommandDialogsPanel_lua": dcs / "Scripts" / "UI" / "RadioCommandDialogPanel" / "CommandDialogsPanel.lua",
        "options_lua": sg / "Config" / "options.lua",
        "SceneVR_lua": dcs / "Scripts" / "DemoScenes" / "SceneVR.lua",
        "autoexec_cfg": sg / "Config" / "autoexec.cfg"
    }
