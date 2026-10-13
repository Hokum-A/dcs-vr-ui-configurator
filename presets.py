from typing import Dict, Any

PRESETS: Dict[str, Dict[str, Any]] = {
    "recommended_vr": {
        "title_ru": "Рекомендуемый (Quest 3 / Оптимальный)",
        "desc_ru": "Сбалансированные размеры для VR. Текст сообщений занимает 1/4 экрана, четкий аккуратный шрифт 13pt (вместо огромного 20pt), радиоменю 1.40x.",
        "title_en": "Recommended (Quest 3 / Optimal)",
        "desc_en": "Balanced VR dimensions. Messages take 1/4 of screen width, crisp 13pt font (instead of 20pt), compact 1.40x radio menu.",
        "settings": {
            "msg_width_mode": "fraction",
            "msg_width_fraction": "1/4",
            "msg_width_fixed": 650,
            "msg_hmd_font_size": 13,
            "radio_hmd_scale": 1.4,
            "radio_width": 280,
            "radio_height": 380
        }
    },
    "fixed_width_vr": {
        "title_ru": "Фиксированная ширина (650 px)",
        "desc_ru": "Ширина окна сообщений жестко зафиксирована на 650px (как в обычном режиме монитора), радиоменю 1.30x.",
        "title_en": "Fixed Width (650 px)",
        "desc_en": "Message box width is fixed at 650px (identical to 2D desktop mode), radio menu 1.30x.",
        "settings": {
            "msg_width_mode": "fixed",
            "msg_width_fraction": "1/4",
            "msg_width_fixed": 650,
            "msg_hmd_font_size": 13,
            "radio_hmd_scale": 1.3,
            "radio_width": 280,
            "radio_height": 380
        }
    },
    "compact_vr": {
        "title_ru": "Компактный (Минимум оверлеев)",
        "desc_ru": "Максимальный обзор вперед. Сообщения занимают лишь 1/5 экрана справа, шрифт 12pt, радиоменю 1.20x.",
        "title_en": "Compact (Minimal Overlays)",
        "desc_en": "Maximum forward visibility. Messages occupy only 1/5 of screen width on the right, 12pt font, ultra-compact 1.20x radio menu.",
        "settings": {
            "msg_width_mode": "fraction",
            "msg_width_fraction": "1/5",
            "msg_width_fixed": 550,
            "msg_hmd_font_size": 12,
            "radio_hmd_scale": 1.2,
            "radio_width": 260,
            "radio_height": 340
        }
    },
    "dcs_default": {
        "title_ru": "Настройки DCS World по умолчанию",
        "desc_ru": "Оригинальные заводские параметры разработчиков DCS: гигантский шрифт 20pt, растягивание на полкабины (1/2 экрана), радиоменю 1.75x.",
        "title_en": "DCS World Default Settings",
        "desc_en": "Original DCS settings: gigantic 20pt font, messages spanning half the cockpit (1/2 screen), 1.75x oversized radio menu.",
        "settings": {
            "msg_width_mode": "fraction",
            "msg_width_fraction": "1/2",
            "msg_width_fixed": 960,
            "msg_hmd_font_size": 20,
            "radio_hmd_scale": 1.75,
            "radio_width": 280,
            "radio_height": 400
        }
    }
}

def get_preset_title(key: str, lang: str = "ru") -> str:
    p = PRESETS.get(key, {})
    return p.get(f"title_{lang}", p.get("title_ru", key))

def get_preset_desc(key: str, lang: str = "ru") -> str:
    p = PRESETS.get(key, {})
    return p.get(f"desc_{lang}", p.get("desc_ru", ""))

def matches_settings(state: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """Checks if state dict matches target settings dict."""
    if not state or not target:
        return False
    keys_to_compare = [
        "msg_width_mode",
        "msg_hmd_font_size",
        "radio_hmd_scale",
        "radio_width",
        "radio_height"
    ]
    for k in keys_to_compare:
        if k not in target or k not in state:
            continue
        v_target = target[k]
        v_state = state[k]
        if isinstance(v_target, float) or isinstance(v_state, float):
            try:
                if abs(float(v_state) - float(v_target)) > 0.02:
                    return False
            except (ValueError, TypeError):
                if v_state != v_target:
                    return False
        else:
            if v_state != v_target:
                return False

    # Check width mode specifics
    if target.get("msg_width_mode") == "fixed":
        if state.get("msg_width_fixed") != target.get("msg_width_fixed"):
            return False
    else:
        if str(state.get("msg_width_fraction")) != str(target.get("msg_width_fraction")):
            return False

    return True

def format_profile_summary(settings: Dict[str, Any], lang: str = "ru") -> str:
    """Formats a concise human-readable one-line summary of settings."""
    if not settings:
        return ""
    mode = settings.get("msg_width_mode", "fraction")
    if mode == "fixed":
        w_str = f"{settings.get('msg_width_fixed', 650)}px"
    else:
        w_str = str(settings.get("msg_width_fraction", "1/3"))

    font_sz = settings.get("msg_hmd_font_size", 13)
    try:
        r_scale = float(settings.get("radio_hmd_scale", 1.1))
    except (ValueError, TypeError):
        r_scale = 1.1

    rw = settings.get("radio_width", 280)
    rh = settings.get("radio_height", 380)

    if lang == "ru":
        return f"Сообщения: {w_str} (шрифт {font_sz}pt) • Меню: {rw}×{rh} ({r_scale:.2f}x)"
    else:
        return f"Messages: {w_str} (font {font_sz}pt) • Menu: {rw}×{rh} ({r_scale:.2f}x)"


def format_profile_detailed(settings: Dict[str, Any], lang: str = "ru") -> str:
    """Formats a detailed multi-line summary for the custom profile card."""
    if not settings:
        return ""

    mode = settings.get("msg_width_mode", "fraction")
    font_sz = settings.get("msg_hmd_font_size", 13)
    try:
        r_scale = float(settings.get("radio_hmd_scale", 1.1))
    except (ValueError, TypeError):
        r_scale = 1.1

    rw = settings.get("radio_width", 280)
    rh = settings.get("radio_height", 380)

    if lang == "ru":
        mode_str = "Доля экрана" if mode == "fraction" else "Фиксированные px"
        if mode == "fixed":
            width_line = f"Ширина: {settings.get('msg_width_fixed', 650)} px"
        else:
            width_line = f"Доля экрана: {settings.get('msg_width_fraction', '1/3')}"
        lines = [
            f"Сообщения: режим «{mode_str}»",
            width_line,
            f"Размер шрифта: {font_sz} pt",
            f"Радиоменю: {rw} × {rh}  •  VR масштаб: {r_scale:.2f}x",
        ]
    else:
        mode_str = "Screen fraction" if mode == "fraction" else "Fixed px"
        if mode == "fixed":
            width_line = f"Width: {settings.get('msg_width_fixed', 650)} px"
        else:
            width_line = f"Fraction: {settings.get('msg_width_fraction', '1/3')}"
        lines = [
            f"Messages: mode \"{mode_str}\"",
            width_line,
            f"Font size: {font_sz} pt",
            f"Radio menu: {rw} × {rh}  •  VR scale: {r_scale:.2f}x",
        ]
    return "\n".join(lines)
