import os
import re
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple, Union


DLSS_PRESET_KEY = "DLSS_Preset"
BOOLEAN_TWEAK_KEYS = (
    "HUD_MFD_after_DLSS",
    "disable_write_track",
    "no_device_hotplug",
    "options.graphics.stereo_mode_use_shared_parser",
)
SUPPORTED_KEYS = (DLSS_PRESET_KEY,) + BOOLEAN_TWEAK_KEYS

ENABLED_TWEAK_VALUES = {
    "HUD_MFD_after_DLSS": True,
    "disable_write_track": True,
    "no_device_hotplug": True,
    "options.graphics.stereo_mode_use_shared_parser": True,
}

AutoexecValue = Union[bool, str, None]


def _without_lua_comment(value: str) -> str:
    quote = None
    escaped = False
    for index, char in enumerate(value):
        if escaped:
            escaped = False
        elif char == "\\" and quote:
            escaped = True
        elif quote:
            if char == quote:
                quote = None
        elif char in ("'", '"'):
            quote = char
        elif value[index:index + 2] == "--":
            return value[:index]
    return value


def read_autoexec_settings(path: Path) -> Tuple[Dict[str, AutoexecValue], Dict[str, str]]:
    values: Dict[str, AutoexecValue] = {key: None for key in SUPPORTED_KEYS}
    errors: Dict[str, str] = {}
    if not path.exists():
        return values, errors

    content = path.read_bytes().decode("utf-8-sig")
    for key in SUPPORTED_KEYS:
        key_pattern = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*?)\s*$")
        assignments = []
        for line in content.splitlines():
            match = key_pattern.match(line)
            if match:
                raw_value = _without_lua_comment(match.group(1)).strip()
                assignments.append(raw_value)

        if len(assignments) > 1:
            errors[key] = "duplicate"
            continue
        if not assignments:
            continue

        raw_value = assignments[0]
        if key == DLSS_PRESET_KEY:
            if raw_value.lower() == "false":
                values[key] = False
                continue
            match = re.fullmatch(r"""(['"])(.*?)(?<!\\)\1""", raw_value)
            if match:
                values[key] = match.group(2)
            else:
                errors[key] = "invalid"
        elif raw_value.lower() in ("true", "false"):
            values[key] = raw_value.lower() == "true"
        else:
            errors[key] = "invalid"

    return values, errors


def write_autoexec_setting(path: Path, key: str, value: AutoexecValue) -> bool:
    if key not in SUPPORTED_KEYS:
        raise ValueError(f"Unsupported autoexec.cfg setting: {key}")
    if key == DLSS_PRESET_KEY:
        if value is False:
            serialized_value = "false"
        elif isinstance(value, str) and re.fullmatch(r"[A-Za-z]", value):
            serialized_value = f"'{value.upper()}'"
        else:
            raise ValueError("DLSS_Preset must be false or a single letter.")
    else:
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be a boolean.")
        serialized_value = "true" if value else "false"

    exists = path.exists()
    original_bytes = path.read_bytes() if exists else b""
    bom = original_bytes.startswith(b"\xef\xbb\xbf")
    content = original_bytes.decode("utf-8-sig") if exists else ""

    _, errors = read_autoexec_settings(path) if exists else ({}, {})
    if key in errors:
        raise ValueError(f"Cannot safely update {key}: {errors[key]}.")

    lines = content.splitlines(keepends=True)
    assignment_pattern = re.compile(rf"^(\s*{re.escape(key)}\s*=\s*)")
    matching_indexes = [
        index for index, line in enumerate(lines)
        if assignment_pattern.match(line.rstrip("\r\n"))
    ]

    if matching_indexes:
        index = matching_indexes[0]
        line = lines[index]
        ending_match = re.search(r"(\r\n|\n|\r)$", line)
        ending = ending_match.group(1) if ending_match else ""
        body = line[:-len(ending)] if ending else line
        prefix_match = assignment_pattern.match(body)
        if prefix_match is None:
            raise ValueError(f"Cannot safely update {key}.")
        remainder = body[prefix_match.end():]
        value_content = _without_lua_comment(remainder)
        if key == DLSS_PRESET_KEY and value_content.strip().lower() != "false":
            token_match = re.match(r"""(['"])(.*?)(?<!\\)\1""", value_content.lstrip())
        else:
            token_match = re.match(r"true|false", value_content.strip(), re.IGNORECASE)
        if token_match is None:
            raise ValueError(f"Cannot safely update {key}.")
        leading_space = len(value_content) - len(value_content.lstrip())
        token_end = leading_space + token_match.end()
        suffix = remainder[token_end:]
        lines[index] = prefix_match.group(1) + serialized_value + suffix + ending
        updated_content = "".join(lines)
    else:
        newline_match = re.search(r"\r\n|\n|\r", content)
        newline = newline_match.group(0) if newline_match else "\n"
        updated_content = content
        if updated_content and not updated_content.endswith(("\r", "\n")):
            updated_content += newline
        updated_content += f"{key} = {serialized_value}{newline}"

    updated_bytes = (b"\xef\xbb\xbf" if bom else b"") + updated_content.encode("utf-8")
    if updated_bytes == original_bytes:
        return False

    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temp_file:
            temp_path = Path(temp_file.name)
            temp_file.write(updated_bytes)
            temp_file.flush()
            os.fsync(temp_file.fileno())
        os.replace(temp_path, path)
        temp_path = None
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass

    return True
