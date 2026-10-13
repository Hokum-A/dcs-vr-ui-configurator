import os
import winreg
from pathlib import Path
from typing import Optional, List

def _check_reg_key(hive, subkey: str, val_name: str) -> Optional[str]:
    try:
        with winreg.OpenKey(hive, subkey) as k:
            val, _ = winreg.QueryValueEx(k, val_name)
            if val and isinstance(val, str) and Path(val).exists():
                return val
    except Exception:
        pass
    return None

def is_valid_dcs_path(path: Path) -> bool:
    """Checks if a directory is a valid DCS World root folder."""
    if not path.is_dir():
        return False
    # Check for gameMessages.lua or DCS executable
    has_gm = (path / "Scripts" / "UI" / "gameMessages.lua").exists()
    has_exe = (path / "bin" / "DCS.exe").exists() or (path / "bin-mt" / "DCS.exe").exists()
    return has_gm or has_exe

def is_valid_saved_games_path(path: Path) -> bool:
    """Checks if a directory is a valid DCS Saved Games folder."""
    if not path.is_dir():
        return False
    return (path / "Config" / "options.lua").exists()

def normalize_dcs_path(raw_path_str: str) -> str:
    """
    Normalizes a path provided by the user.
    If the user selected DCS.exe or bin/ or Scripts/, walks up to the root folder.
    """
    if not raw_path_str:
        return raw_path_str
    
    p = Path(raw_path_str.strip(' \t\n\r"\''))
    if p.is_file():
        p = p.parent

    # If user selected bin, bin-mt, Scripts, or Scripts/UI, walk up
    for _ in range(3):
        if is_valid_dcs_path(p):
            return str(p)
        if p.name.lower() in ("bin", "bin-mt", "scripts", "ui"):
            p = p.parent
        else:
            break

    if is_valid_dcs_path(p):
        return str(p)

    return str(Path(raw_path_str))

def detect_dcs_install_path() -> Optional[str]:
    """Attempts to automatically find DCS World installation directory."""
    # 1. Check Eagle Dynamics Registry
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for subkey in (
            r"SOFTWARE\Eagle Dynamics\DCS World OpenBeta",
            r"SOFTWARE\Eagle Dynamics\DCS World",
            r"SOFTWARE\WOW6432Node\Eagle Dynamics\DCS World OpenBeta",
            r"SOFTWARE\WOW6432Node\Eagle Dynamics\DCS World"
        ):
            p = _check_reg_key(hive, subkey, "Path")
            if p and is_valid_dcs_path(Path(p)):
                return str(Path(p))

    # 2. Check Steam Registry (App ID 223750)
    for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for subkey in (
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 223750",
            r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall\Steam App 223750"
        ):
            p = _check_reg_key(hive, subkey, "InstallLocation")
            if p and is_valid_dcs_path(Path(p)):
                return str(Path(p))

    # 3. Scan existing drive letters
    drives = [f"{chr(c)}:\\" for c in range(ord('C'), ord('Z') + 1) if os.path.exists(f"{chr(c)}:\\")]
    candidates = [
        r"Program Files\Eagle Dynamics\DCS World OpenBeta",
        r"Program Files\Eagle Dynamics\DCS World",
        r"Eagle Dynamics\DCS World OpenBeta",
        r"Eagle Dynamics\DCS World",
        r"Games\DCS World OpenBeta",
        r"Games\DCS World",
        r"GAMES\DCS World OpenBeta",
        r"GAMES\DCS World",
        r"DCS World OpenBeta",
        r"DCS World",
        r"SteamLibrary\steamapps\common\DCSWorld",
        r"Program Files (x86)\Steam\steamapps\common\DCSWorld",
        r"Steam\steamapps\common\DCSWorld"
    ]

    for drive in drives:
        for rel in candidates:
            cand = Path(drive) / rel
            if is_valid_dcs_path(cand):
                return str(cand)

    return None

def detect_saved_games_path() -> Optional[str]:
    """Attempts to find DCS Saved Games directory containing Config/options.lua."""
    saved_games_roots: List[Path] = []

    # 1. Query Windows User Shell Folders for Saved Games GUID
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
            sg_val, _ = winreg.QueryValueEx(k, "{4C5C32FF-BB9D-43B0-B5B4-2D72E54EAAA4}")
            if sg_val:
                expanded = os.path.expandvars(sg_val)
                p = Path(expanded)
                if p.exists():
                    saved_games_roots.append(p)
    except Exception:
        pass

    # 2. Standard user home fallback
    home_sg = Path.home() / "Saved Games"
    if home_sg.exists() and home_sg not in saved_games_roots:
        saved_games_roots.append(home_sg)

    # Search candidates inside Saved Games
    for root in saved_games_roots:
        for folder_name in ("DCS.openbeta", "DCS", "DCS World"):
            cand = root / folder_name
            if is_valid_saved_games_path(cand):
                return str(cand)

    # Return default candidate even if options.lua doesn't exist yet
    for root in saved_games_roots:
        for folder_name in ("DCS.openbeta", "DCS"):
            cand = root / folder_name
            if cand.exists():
                return str(cand)

    return str(Path.home() / "Saved Games" / "DCS.openbeta")
