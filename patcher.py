import re
from pathlib import Path
from typing import Dict, Any, Tuple, List

HIGH_WIDGET_NAMES = [
    "autoScrollTextRadio_High",
    "autoScrollTextTrig_High",
    "sMain_High",
    "sRadioAuto_High"
]

def read_current_state(target_files: Dict[str, Path]) -> Dict[str, Any]:
    state = {
        "msg_width_mode": "fraction",   # "fraction" or "fixed"
        "msg_width_fraction": "1/2",    # "1/2", "1/3", "1/4", etc.
        "msg_width_fixed": 650,         # pixels
        "msg_hmd_font_size": 20,
        "radio_hmd_scale": 1.75,
        "radio_width": 280,
        "radio_height": 400,
        "options_messages_font_scale": 1.0,
        "options_custom_ipd": 63,
        "options_box_mouse_cursor": True,
        "files_found": {}
    }

    # 1. gameMessages.lua
    gm_path = target_files.get("gameMessages_lua")
    if gm_path and gm_path.exists():
        state["files_found"]["gameMessages_lua"] = True
        try:
            content = gm_path.read_text(encoding="utf-8")
            # Width in VR
            w_match = re.search(r"if\s+HMD\.isActive\(\)\s+then\s*width\s*=\s*([^\r\n]+)", content)
            if w_match:
                raw_w = w_match.group(1).strip()
                if "main_w" in raw_w:
                    state["msg_width_mode"] = "fraction"
                    if "main_w / 2" in raw_w:
                        state["msg_width_fraction"] = "1/2"
                    elif "main_w / 3" in raw_w:
                        state["msg_width_fraction"] = "1/3"
                    elif "main_w / 4" in raw_w:
                        state["msg_width_fraction"] = "1/4"
                    elif "main_w / 5" in raw_w:
                        state["msg_width_fraction"] = "1/5"
                    else:
                        state["msg_width_fraction"] = raw_w.replace("main_w /", "").strip()
                else:
                    state["msg_width_mode"] = "fixed"
                    num = re.sub(r"[^\d]", "", raw_w)
                    if num:
                        state["msg_width_fixed"] = int(num)
            
        except Exception as e:
            print(f"Error reading gameMessages.lua: {e}")
    else:
        state["files_found"]["gameMessages_lua"] = False

    # 2. gameMessages.dlg
    dlg_path = target_files.get("gameMessages_dlg")
    if dlg_path and dlg_path.exists():
        state["files_found"]["gameMessages_dlg"] = True
        try:
            content = dlg_path.read_text(encoding="utf-8")
            m = re.search(r'\["autoScrollTextTrig_High"\][\s\S]*?\["fontSize"\]\s*=\s*(\d+)', content)
            if m:
                state["msg_hmd_font_size"] = int(m.group(1))
        except Exception as e:
            print(f"Error reading gameMessages.dlg: {e}")
    else:
        state["files_found"]["gameMessages_dlg"] = False

    # 3. CommandMenu.lua
    cm_path = target_files.get("CommandMenu_lua")
    if cm_path and cm_path.exists():
        state["files_found"]["CommandMenu_lua"] = True
        try:
            content = cm_path.read_text(encoding="utf-8")
            s_match = re.search(r"if\s+HMD\.isActive\(\)\s+then[\s\S]*?fontScale\s*=\s*fontScale\s*\*\s*([\d\.]+)", content)
            if s_match:
                state["radio_hmd_scale"] = float(s_match.group(1))
            w_match = re.search(r"function\s+getMenuWidth\(\)[\s\S]*?return\s+(\d+)\s*\*\s*fontScale", content)
            if w_match:
                state["radio_width"] = int(w_match.group(1))
            h_match = re.search(r"function\s+getMenuHeight\(\)[\s\S]*?return\s+(\d+)\s*\*\s*fontScale", content)
            if h_match:
                state["radio_height"] = int(h_match.group(1))
        except Exception as e:
            print(f"Error reading CommandMenu.lua: {e}")
    else:
        state["files_found"]["CommandMenu_lua"] = False

    # 4. options.lua
    opt_path = target_files.get("options_lua")
    if opt_path and opt_path.exists():
        state["files_found"]["options_lua"] = True
        try:
            content = opt_path.read_text(encoding="utf-8")
            fs_match = re.search(r'\["messagesFontScale"\]\s*=\s*([\d\.]+)', content)
            if fs_match:
                state["options_messages_font_scale"] = float(fs_match.group(1))
            ipd_match = re.search(r'\["custom_IPD"\]\s*=\s*([\d\.]+)', content)
            if ipd_match:
                state["options_custom_ipd"] = int(float(ipd_match.group(1)))
            box_match = re.search(r'\["box_mouse_cursor"\]\s*=\s*(true|false)', content)
            if box_match:
                state["options_box_mouse_cursor"] = (box_match.group(1) == "true")
        except Exception as e:
            print(f"Error reading options.lua: {e}")
    else:
        state["files_found"]["options_lua"] = False

    return state

def apply_settings(target_files: Dict[str, Path], settings: Dict[str, Any]) -> Tuple[bool, List[str], List[str]]:
    errors = []
    updated_files = []

    # 1. Patch gameMessages.lua
    gm_path = target_files.get("gameMessages_lua")
    if gm_path and gm_path.exists():
        try:
            original_content = gm_path.read_text(encoding="utf-8")
            content = original_content

            # Determine width replacement
            if settings.get("msg_width_mode") == "fixed":
                fixed_val = settings.get("msg_width_fixed", 650)
                width_expr = f"width = {fixed_val}"
            else:
                frac = settings.get("msg_width_fraction", "1/3")
                if frac.startswith("1/"):
                    div = frac.split("1/")[1]
                    width_expr = f"width = main_w / {div}"
                else:
                    width_expr = "width = main_w / 3"

            # Replace width in HMD block
            content, _ = re.subn(
                r"(if\s+HMD\.isActive\(\)\s+then\s*\n\s*)width\s*=\s*[^\r\n]+",
                rf"\g<1>{width_expr}",
                content
            )

            if content != original_content:
                gm_path.write_text(content, encoding="utf-8")
                updated_files.append("gameMessages.lua")
        except Exception as e:
            errors.append(f"gameMessages.lua: {e}")

    # 2. Patch gameMessages.dlg (Font size in _High widgets)
    dlg_path = target_files.get("gameMessages_dlg")
    if dlg_path and dlg_path.exists():
        try:
            original_content = dlg_path.read_text(encoding="utf-8")
            content = original_content
            target_font_size = int(settings.get("msg_hmd_font_size", 13))

            # Replace fontSize inside the 4 High blocks
            for widget in HIGH_WIDGET_NAMES:
                pattern = rf'(\["{widget}"\][\s\S]*?\["fontSize"\]\s*=\s*)\d+'
                content, _ = re.subn(pattern, rf"\g<1>{target_font_size}", content, count=1)

            if content != original_content:
                dlg_path.write_text(content, encoding="utf-8")
                updated_files.append("gameMessages.dlg")
        except Exception as e:
            errors.append(f"gameMessages.dlg: {e}")

    # 3. Patch CommandMenu.lua
    cm_path = target_files.get("CommandMenu_lua")
    if cm_path and cm_path.exists():
        try:
            original_content = cm_path.read_text(encoding="utf-8")
            content = original_content
            radio_scale = float(settings.get("radio_hmd_scale", 1.1))
            radio_w = int(settings.get("radio_width", 280))
            radio_h = int(settings.get("radio_height", 380))

            content, _ = re.subn(
                r"(if\s+HMD\.isActive\(\)\s+then\s*\n\s*)fontScale\s*=\s*fontScale\s*\*\s*[\d\.]+",
                rf"\g<1>fontScale = fontScale * {radio_scale:.2f}".rstrip("0").rstrip("."),
                content
            )

            content, _ = re.subn(
                r"(function\s+getMenuWidth\(\)[\s\S]*?return\s+)\d+(\s*\*\s*fontScale)",
                rf"\g<1>{radio_w}\g<2>",
                content
            )

            content, _ = re.subn(
                r"(function\s+getMenuHeight\(\)[\s\S]*?return\s+)\d+(\s*\*\s*fontScale)",
                rf"\g<1>{radio_h}\g<2>",
                content
            )

            if content != original_content:
                cm_path.write_text(content, encoding="utf-8")
                updated_files.append("CommandMenu.lua")
        except Exception as e:
            errors.append(f"CommandMenu.lua: {e}")

    # 4. Patch options.lua
    opt_path = target_files.get("options_lua")
    if opt_path and opt_path.exists():
        try:
            original_content = opt_path.read_text(encoding="utf-8")
            content = original_content

            if "options_custom_ipd" in settings:
                ipd = int(settings["options_custom_ipd"])
                content, _ = re.subn(
                    r'(\["custom_IPD"\]\s*=\s*)[\d\.]+',
                    rf"\g<1>{ipd}",
                    content
                )

            if "options_box_mouse_cursor" in settings:
                box_cursor = "true" if settings["options_box_mouse_cursor"] else "false"
                content, _ = re.subn(
                    r'(\["box_mouse_cursor"\]\s*=\s*)(true|false)',
                    rf"\g<1>{box_cursor}",
                    content
                )

            if content != original_content:
                opt_path.write_text(content, encoding="utf-8")
                updated_files.append("options.lua")
        except Exception as e:
            errors.append(f"options.lua: {e}")

    if errors:
        return False, updated_files, errors
    return True, updated_files, []
