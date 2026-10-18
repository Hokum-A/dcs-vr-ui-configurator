import json
import os
import re
import shutil
import tempfile
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Optional, Tuple

from config import BACKUPS_DIR, ORIGINAL_BACKUPS_DIR

_TARGET_ALTITUDE = "1"
_TARGET_ALTITUDE_TYPE = "RADIO"
_NUMBER_PATTERN = rb"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?"
_WAYPOINT_DEFAULTS_PATTERN = re.compile(
    rb"(?m)^[ \t]*waypoint\.action[ \t]*=[ \t]*[\"']Turning Point[\"'][^\r\n]*\r?\n"
    rb"^[ \t]*waypoint\.type[ \t]*=[ \t]*[\"']Turning Point[\"'][^\r\n]*\r?\n"
    rb"^[ \t]*waypoint\.alt[ \t]*=[ \t]*(?P<alt>"
    + _NUMBER_PATTERN
    + rb")[ \t]*(?:--[^\r\n]*)?\r?\n"
    rb"^[ \t]*waypoint\.alt_type[ \t]*=[ \t]*(?P<quote>[\"'])"
    rb"(?P<alt_type>BARO|RADIO)(?P=quote)[^\r\n]*"
)


class RouteToolError(ValueError):
    """Raised when the current RouteTool.lua format cannot be edited safely."""


def _find_assignment_block(content: bytes) -> re.Match:
    function_matches = list(re.finditer(rb"(?m)^function\s+addWaypoint\s*\(", content))
    if len(function_matches) != 1:
        raise RouteToolError("Could not uniquely locate addWaypoint in RouteTool.lua.")

    start = function_matches[0].start()
    end_match = re.search(rb"(?m)^function\s+deleteWaypoint\s*\(", content[start:])
    if not end_match:
        raise RouteToolError("Could not locate the end of addWaypoint in RouteTool.lua.")

    matches = list(_WAYPOINT_DEFAULTS_PATTERN.finditer(content, start, start + end_match.start()))
    if len(matches) != 1:
        raise RouteToolError(
            "Could not uniquely locate the first-waypoint altitude settings in addWaypoint."
        )
    return matches[0]


def _get_defaults(content: bytes) -> Tuple[str, str, re.Match]:
    match = _find_assignment_block(content)
    altitude = match.group("alt").decode("ascii")
    altitude_type = match.group("alt_type").decode("ascii")
    return altitude, altitude_type, match


def read_route_tool_defaults(path: Path) -> Tuple[str, str]:
    content = path.read_bytes()
    altitude, altitude_type, _ = _get_defaults(content)
    return altitude, altitude_type


def is_route_tool_enabled(defaults: Tuple[str, str]) -> bool:
    try:
        return Decimal(defaults[0]) == Decimal(_TARGET_ALTITUDE) and defaults[1] == _TARGET_ALTITUDE_TYPE
    except InvalidOperation:
        return False


def _state_key(path: Path) -> str:
    return str(path.resolve()).casefold()


def _read_saved_defaults(state_path: Path, route_path: Path) -> Optional[Tuple[str, str]]:
    if not state_path.exists():
        return None

    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RouteToolError(f"Could not read saved Route Tool defaults: {error}") from error

    if not isinstance(data, dict):
        raise RouteToolError("Saved Route Tool defaults have an unsupported format.")
    defaults = data.get(_state_key(route_path))
    if defaults is None:
        return None
    if (
        not isinstance(defaults, dict)
        or not isinstance(defaults.get("alt"), str)
        or not re.fullmatch(r"[-+]?\d+(?:\.\d*)?(?:[eE][-+]?\d+)?", defaults["alt"])
        or defaults.get("alt_type") not in ("BARO", "RADIO")
    ):
        raise RouteToolError("Saved Route Tool defaults have an unsupported format.")
    return defaults["alt"], defaults["alt_type"]


def _save_defaults(
    state_path: Path,
    route_path: Path,
    defaults: Tuple[str, str]
) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    data: Dict[str, dict] = {}
    if state_path.exists():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            raise RouteToolError(f"Could not read saved Route Tool defaults: {error}") from error
        if not isinstance(loaded, dict):
            raise RouteToolError("Saved Route Tool defaults have an unsupported format.")
        data = loaded

    data[_state_key(route_path)] = {"alt": defaults[0], "alt_type": defaults[1]}
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=state_path.parent,
            prefix=f".{state_path.name}.",
            suffix=".tmp",
            delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            json.dump(data, temporary_file, indent=2, ensure_ascii=False)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, state_path)
    except OSError as error:
        raise RouteToolError(f"Could not save Route Tool defaults: {error}") from error
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def _original_defaults(route_path: Path) -> Optional[Tuple[str, str]]:
    original_path = ORIGINAL_BACKUPS_DIR / route_path.name
    if not original_path.exists():
        return None
    try:
        defaults = read_route_tool_defaults(original_path)
    except (OSError, RouteToolError):
        return None
    if is_route_tool_enabled(defaults):
        return None
    return defaults


def read_original_route_tool_defaults(route_path: Path) -> Tuple[str, str]:
    original_path = ORIGINAL_BACKUPS_DIR / route_path.name
    if not original_path.is_file():
        raise RouteToolError(f"Original backup not found: {original_path}")
    try:
        defaults = read_route_tool_defaults(original_path)
    except (OSError, RouteToolError) as error:
        raise RouteToolError(f"Could not read original backup {original_path}: {error}") from error
    if is_route_tool_enabled(defaults):
        raise RouteToolError(f"Original backup has modified waypoint settings: {original_path}")
    return defaults


def ensure_route_tool_original_backup(route_path: Path) -> bool:
    """Preserve a valid baseline and repair an invalid one from an unmodified file."""
    original_path = ORIGINAL_BACKUPS_DIR / route_path.name
    if original_path.is_file():
        try:
            original_defaults = read_route_tool_defaults(original_path)
            if not is_route_tool_enabled(original_defaults):
                return True
        except (OSError, RouteToolError):
            pass

    if not route_path.is_file():
        return False
    try:
        defaults = read_route_tool_defaults(route_path)
        if is_route_tool_enabled(defaults):
            return False
        ORIGINAL_BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copy2(route_path, original_path)
        return read_original_route_tool_defaults(route_path) == defaults
    except (OSError, RouteToolError):
        return False


def ensure_route_tool_baseline(route_path: Path) -> bool:
    """Seed a baseline for an already-enabled file from its preserved original, if available."""
    if not route_path.exists():
        return False
    current = read_route_tool_defaults(route_path)
    if not is_route_tool_enabled(current):
        return True

    state_path = BACKUPS_DIR / "route_tool_defaults.json"
    if _read_saved_defaults(state_path, route_path) is not None:
        return True
    baseline = _original_defaults(route_path)
    if baseline is not None:
        _save_defaults(state_path, route_path, baseline)
        return True
    return False


def _replace_defaults(
    route_path: Path,
    content: bytes,
    match: re.Match,
    defaults: Tuple[str, str]
) -> None:
    replacements = (
        (match.start("alt"), match.end("alt"), defaults[0].encode("ascii")),
        (match.start("alt_type"), match.end("alt_type"), defaults[1].encode("ascii")),
    )
    updated = content
    for start, end, replacement in sorted(replacements, reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    if updated == content:
        return

    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=route_path.parent,
            prefix=f".{route_path.name}.",
            suffix=".tmp",
            delete=False
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(updated)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, route_path)
    except OSError as error:
        raise RouteToolError(f"Could not update RouteTool.lua: {error}") from error
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def set_route_tool_enabled(route_path: Path, enabled: bool) -> bool:
    """Change only the first-waypoint altitude and type, retaining the rest of the Lua file."""
    content = route_path.read_bytes()
    current_altitude, current_type, match = _get_defaults(content)
    current = (current_altitude, current_type)
    state_path = BACKUPS_DIR / "route_tool_defaults.json"
    already_enabled = is_route_tool_enabled(current)

    if enabled:
        if already_enabled:
            if _read_saved_defaults(state_path, route_path) is None:
                baseline = _original_defaults(route_path)
                if baseline is None:
                    raise RouteToolError(
                        "The current file is already enabled, but its original waypoint defaults "
                        "could not be found. No file changes were made."
                    )
                _save_defaults(state_path, route_path, baseline)
            return False
        _save_defaults(state_path, route_path, current)
        target = (_TARGET_ALTITUDE, _TARGET_ALTITUDE_TYPE)
    else:
        if not already_enabled:
            return False
        baseline = _read_saved_defaults(state_path, route_path) or _original_defaults(route_path)
        if baseline is None:
            raise RouteToolError(
                "Could not find the original waypoint defaults. No file changes were made."
            )
        if is_route_tool_enabled(baseline):
            raise RouteToolError("The saved original waypoint defaults are not valid.")
        target = baseline

    _replace_defaults(route_path, content, match, target)
    return True


def restore_route_tool_original(route_path: Path) -> bool:
    """Restore only the first waypoint altitude values from the preserved original backup."""
    original_defaults = read_original_route_tool_defaults(route_path)
    content = route_path.read_bytes()
    current_altitude, current_type, match = _get_defaults(content)
    if (current_altitude, current_type) == original_defaults:
        return False

    _replace_defaults(route_path, content, match, original_defaults)
    _save_defaults(
        BACKUPS_DIR / "route_tool_defaults.json",
        route_path,
        original_defaults
    )
    return True
