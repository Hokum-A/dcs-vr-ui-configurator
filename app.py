import os
import sys
import webbrowser
import tkinter as tk
from tkinter import filedialog
import tkinter.font as tkfont
import customtkinter as ctk
from pathlib import Path
from PIL import Image, ImageDraw, ImageTk

from config import (
    load_settings,
    save_settings,
    get_target_files,
    APP_VERSION,
)
from backup_manager import (
    ensure_clean_backup,
    restore_clean_original
)
from patcher import read_current_state, apply_settings
from presets import PRESETS, get_preset_title, get_preset_desc, matches_settings, format_profile_summary, format_profile_detailed
from translations import t
from path_detector import detect_dcs_install_path, detect_saved_games_path, normalize_dcs_path

# Configure CustomTkinter
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

# Color Palette inspired by DCS Translation Tool (Dark Charcoal + Amber/Orange #ff9900)
THEME = {
    "bg_main": "#1a1b1e",
    "header_bg": "#222327",
    "action_bar_bg": "#26272c",
    "card_bg": "#2a2b31",
    "card_border": "#3c3e47",
    "sub_box_bg": "#1f2025",
    
    # Amber / Orange accent (Matching DCS Translation Tool #ff9900)
    "accent_amber": "#ff9900",
    "accent_amber_hover": "#e68a00",
    "accent_gold": "#ff9900",
    "accent_dark_text": "#000000",
    
    # Graphite / Neutral buttons
    "btn_gray": "#383a42",
    "btn_gray_hover": "#464954",
    
    # Green action (One-click reapply & status)
    "green_action": "#16a34a",
    "green_action_hover": "#15803d",
    
    # Status badges (No background, subtle text colors)
    "status_green_text": "#86efac",
    "status_red_text": "#f87171",
    "status_amber_text": "#fde047",
    
    # Text colors
    "text_title": "#ff9900",
    "text_primary": "#f3f4f6",
    "text_secondary": "#a1a1aa",
    "text_muted": "#71717a"
}


class LanguageToggleSwitch(tk.Canvas):
    """
    Compact language toggle switch styled identically to DCS Translation Tool:
    - Fixed dimensions: 30x14 px
    - Pill shaped track with radius 7 px
    - Red (#ff3333) when RU, Blue (#3366ff) when EN
    - Smooth 13x13 px circular thumb (#f0f0f0) with 4x supersampling anti-aliasing
    - Smooth sliding animation between EN (left, pos=2) and RU (right, pos=17)
    - Clicking toggles language state and calls command(lang)
    """
    def __init__(self, parent, bg_color="#222327", initial_lang="ru", command=None):
        super().__init__(
            parent,
            width=30,
            height=14,
            bg=bg_color,
            highlightthickness=0,
            bd=0,
            cursor="hand2"
        )
        self._checked = (initial_lang == "ru")
        self._command = command
        self._bg_color = bg_color

        # Pre-render anti-aliased frames (positions 2 to 17) using supersampling
        self._frames = {}
        for pos in [2, 5, 8, 11, 14, 17]:
            t_ratio = (pos - 2) / 15.0
            r = int(51 + (255 - 51) * t_ratio)
            g = int(102 + (51 - 102) * t_ratio)
            b = int(255 + (51 - 255) * t_ratio)

            scale = 4
            w_scaled, h_scaled = 30 * scale, 14 * scale
            img = Image.new("RGBA", (w_scaled, h_scaled), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            # Draw rounded pill track
            draw.rounded_rectangle([0, 0, w_scaled - 1, h_scaled - 1], radius=7 * scale, fill=(r, g, b, 255))

            # Draw thumb circle (13x13)
            kx = (pos - 1) * scale
            ky = 0.5 * scale
            kw = 13 * scale
            kh = 13 * scale
            draw.ellipse([kx, ky, kx + kw, ky + kh], fill=(240, 240, 240, 255))

            resized = img.resize((30, 14), Image.Resampling.LANCZOS)
            self._frames[pos] = ImageTk.PhotoImage(resized)

        self._current_pos = 17 if self._checked else 2
        self._image_item = self.create_image(0, 0, anchor="nw", image=self._frames[self._current_pos])
        self.bind("<Button-1>", self._on_click)

    def _on_click(self, event=None):
        self.toggle()

    def toggle(self):
        self.set_checked(not self._checked, animate=True)

    def is_checked(self) -> bool:
        return self._checked

    def get_lang(self) -> str:
        return "ru" if self._checked else "en"

    def set_checked(self, checked: bool, animate: bool = True):
        self._checked = checked
        target_pos = 17 if self._checked else 2

        if animate:
            self._animate_to(target_pos)
        else:
            self._current_pos = target_pos
            self.itemconfig(self._image_item, image=self._frames[self._current_pos])

        if self._command:
            self._command(self.get_lang())

    def _animate_to(self, target_pos: int):
        positions = [2, 5, 8, 11, 14, 17] if target_pos == 17 else [17, 14, 11, 8, 5, 2]

        def step(idx):
            if idx < len(positions):
                pos = positions[idx]
                self._current_pos = pos
                self.itemconfig(self._image_item, image=self._frames[pos])
                self.after(20, lambda: step(idx + 1))

        step(0)


class PillButton(ctk.CTkButton):
    """
    Pill-shaped button rendered with 4x supersampled anti-aliased PIL curves:
    - Left and right ends are mathematically perfect 180° semicircles (radius = height / 2)
    - Zero vertical flat segments, zero staircase / aliasing artifacts
    - Smooth hover color transitions
    - Seamless integration with CTkButton features (command, text, state, etc.)
    """
    def __init__(self, *args, **kwargs):
        self._pill_images = {}
        self._mouse_inside = False
        super().__init__(*args, **kwargs)

    def _draw(self, no_color_updates=False):
        if not hasattr(self, '_pill_images'):
            self._pill_images = {}
        super()._draw(no_color_updates)

        self._canvas.delete("inner_parts")
        self._canvas.delete("border_parts")
        self._canvas.delete("background_parts")

        w = int(round(self._apply_widget_scaling(self._current_width)))
        h = int(round(self._apply_widget_scaling(self._current_height)))
        if w <= 0 or h <= 0:
            return

        fg_col = self._apply_appearance_mode(self._fg_color)
        hover_col = self._apply_appearance_mode(self._hover_color)
        bg_col = self._apply_appearance_mode(self._bg_color)
        self._canvas.configure(bg=bg_col)

        key_normal = (w, h, fg_col)
        key_hover = (w, h, hover_col)

        scale = 4
        W, H = w * scale, h * scale
        r = (H - 1) / 2.0  # true mathematical semicircle radius

        if key_normal not in self._pill_images:
            img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle([0, 0, W - 1, H - 1], radius=r, fill=fg_col)
            resized = img.resize((w, h), Image.Resampling.LANCZOS)
            self._pill_images[key_normal] = ImageTk.PhotoImage(resized)

        if key_hover not in self._pill_images:
            img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            draw.rounded_rectangle([0, 0, W - 1, H - 1], radius=r, fill=hover_col)
            resized = img.resize((w, h), Image.Resampling.LANCZOS)
            self._pill_images[key_hover] = ImageTk.PhotoImage(resized)

        is_hovered = getattr(self, "_mouse_inside", False)
        current_img = self._pill_images[key_hover] if is_hovered else self._pill_images[key_normal]

        if not self._canvas.find_withtag("pill_bg"):
            self._canvas.create_image(0, 0, anchor="nw", image=current_img, tags="pill_bg")
        else:
            self._canvas.itemconfig("pill_bg", image=current_img)
            self._canvas.coords("pill_bg", 0, 0)

        self._canvas.tag_lower("pill_bg")

        if self._text_label is not None:
            active_col = hover_col if is_hovered else fg_col
            self._text_label.configure(bg=active_col)

    def _on_enter(self, event=None):
        super()._on_enter(event)
        w = int(round(self._apply_widget_scaling(self._current_width)))
        h = int(round(self._apply_widget_scaling(self._current_height)))
        hover_col = self._apply_appearance_mode(self._hover_color)
        key_hover = (w, h, hover_col)
        if key_hover in self._pill_images:
            self._canvas.itemconfig("pill_bg", image=self._pill_images[key_hover])

    def _on_leave(self, event=None):
        super()._on_leave(event)
        w = int(round(self._apply_widget_scaling(self._current_width)))
        h = int(round(self._apply_widget_scaling(self._current_height)))
        fg_col = self._apply_appearance_mode(self._fg_color)
        key_normal = (w, h, fg_col)
        if key_normal in self._pill_images:
            self._canvas.itemconfig("pill_bg", image=self._pill_images[key_normal])


class PremiumRadioButton(ctk.CTkRadioButton):
    """
    Minimalist premium radio button rendered with 4x supersampled PIL curves:
    - Checked: Vibrant amber disc (#ff9900) with a sleek centered dark dot (#1a1b1e).
    - Unchecked: Modern dark disc (#1f2025) with a crisp subtle gray outline (#555864).
    - Hover: Outline illuminates in amber (#ffaa00).
    """
    def __init__(self, *args, **kwargs):
        self._radio_images = {}
        self._is_hovered = False
        kwargs.setdefault("radiobutton_width", 18)
        kwargs.setdefault("radiobutton_height", 18)
        super().__init__(*args, **kwargs)

    def _get_radio_image(self, size, checked, hovered):
        key = (size, checked, hovered)
        if key in self._radio_images:
            return self._radio_images[key]
        scale = 4
        S = size * scale
        img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        cx, cy = S / 2.0, S / 2.0

        if checked:
            draw.ellipse([0, 0, S - 1, S - 1], fill="#ff9900")
            dot_r = 3.0 * scale
            draw.ellipse([cx - dot_r, cy - dot_r, cx + dot_r, cy + dot_r], fill="#1a1b1e")
        elif hovered:
            draw.ellipse([0, 0, S - 1, S - 1], fill="#25272e", outline="#ffaa00", width=int(1.5 * scale))
        else:
            draw.ellipse([0, 0, S - 1, S - 1], fill="#1f2025", outline="#555864", width=int(1.5 * scale))

        resized = img.resize((size, size), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(resized)
        self._radio_images[key] = photo
        return photo

    def _draw(self, no_color_updates=False):
        super()._draw(no_color_updates)
        self._canvas.delete("inner_parts")
        self._canvas.delete("border_parts")

        size = self._radiobutton_width
        is_checked = getattr(self, "_check_state", False)
        is_hovered = getattr(self, "_is_hovered", False)
        photo = self._get_radio_image(size, is_checked, is_hovered)

        if not self._canvas.find_withtag("premium_radio"):
            self._canvas.create_image(0, 0, anchor="nw", image=photo, tags="premium_radio")
        else:
            self._canvas.itemconfig("premium_radio", image=photo)
            self._canvas.coords("premium_radio", 0, 0)
        self._canvas.tag_lower("premium_radio")

    def _on_enter(self, event=0):
        super()._on_enter(event)
        self._is_hovered = True
        self._draw()

    def _on_leave(self, event=0):
        super()._on_leave(event)
        self._is_hovered = False
        self._draw()


class HoverTooltip:
    def __init__(self, widget, text_provider):
        self.widget = widget
        self.text_provider = text_provider
        self._timer = None
        self._window = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")

    def _schedule(self, event=None):
        self._cancel_timer()
        self._timer = self.widget.after(500, self._show)

    def _show(self):
        self._timer = None
        text = self.text_provider()
        if not text or not self.widget.winfo_exists():
            return
        self._window = tk.Toplevel(self.widget)
        self._window.wm_overrideredirect(True)
        self._window.configure(bg="#111216")
        label = tk.Label(
            self._window,
            text=text,
            justify="left",
            wraplength=360,
            bg="#111216",
            fg=THEME["text_primary"],
            padx=9,
            pady=6,
            relief="solid",
            borderwidth=1
        )
        label.pack()
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self._window.geometry(f"+{x}+{y}")

    def _cancel_timer(self):
        if self._timer is not None:
            self.widget.after_cancel(self._timer)
            self._timer = None

    def _hide(self, event=None):
        self._cancel_timer()
        if self._window is not None:
            self._window.destroy()
            self._window = None


class DLSSPresetPicker(ctk.CTkFrame):
    def __init__(self, master, command):
        super().__init__(master, fg_color="transparent", width=54, height=24)
        self._command = command
        self._popup = None
        self._disabled = False
        self._suppress_focus_commit = False

        self._entry = ctk.CTkEntry(
            self,
            width=30,
            height=24,
            corner_radius=4,
            border_width=1,
            border_color="#555864",
            fg_color=THEME["sub_box_bg"],
            text_color=THEME["text_primary"],
            font=ctk.CTkFont(size=12)
        )
        self._entry.pack(side="left", fill="y")
        self._arrow = ctk.CTkButton(
            self,
            text="▾",
            width=20,
            height=24,
            corner_radius=4,
            fg_color=THEME["btn_gray"],
            hover_color=THEME["btn_gray_hover"],
            text_color=THEME["text_primary"],
            font=ctk.CTkFont(size=11),
            command=self._toggle_popup
        )
        self._arrow.pack(side="left", padx=(2, 0))
        self._entry.bind("<Return>", self._commit_entry)
        self._entry.bind("<FocusOut>", self._schedule_focus_commit, add="+")
        self.bind("<Destroy>", self._on_destroy, add="+")

    def get(self):
        return self._entry.get()

    def set(self, value):
        self._entry.delete(0, "end")
        self._entry.insert(0, value)

    def configure(self, **kwargs):
        state = kwargs.pop("state", None)
        super().configure(**kwargs)
        if state is not None:
            self._disabled = state == "disabled"
            widget_state = "disabled" if self._disabled else "normal"
            self._entry.configure(state=widget_state)
            self._arrow.configure(state=widget_state)
            if self._disabled:
                self._close_popup()

    def _toggle_popup(self):
        if self._disabled:
            return
        if self._popup is not None:
            self._close_popup()
            return

        popup = ctk.CTkToplevel(self.winfo_toplevel())
        popup.withdraw()
        popup.overrideredirect(True)
        popup.transient(self.winfo_toplevel())

        frame = ctk.CTkFrame(
            popup,
            fg_color=THEME["card_bg"],
            border_width=1,
            border_color="#656873",
            corner_radius=4
        )
        frame.pack(fill="both", expand=True)
        for value in ("J", "K", "L", "M"):
            button = ctk.CTkButton(
                frame,
                text=value,
                anchor="w",
                height=21,
                corner_radius=2,
                fg_color="transparent",
                hover_color=THEME["btn_gray_hover"],
                text_color=THEME["text_primary"],
                font=ctk.CTkFont(size=12),
                command=lambda selected=value: self._select_value(selected)
            )
            button.pack(fill="x", padx=2, pady=1)

        self._popup = popup
        popup.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        popup.geometry(f"{max(self.winfo_width(), 62)}x{popup.winfo_reqheight()}+{x}+{y}")
        popup.deiconify()
        popup.lift()

    def _select_value(self, value):
        self._suppress_focus_commit = True
        self.set(value)
        self._close_popup()
        self._command(value)
        self.after(200, self._clear_focus_commit_suppression)

    def _commit_entry(self, event=None):
        self._command(self.get())
        return "break"

    def _schedule_focus_commit(self, event=None):
        if not self._suppress_focus_commit:
            self.after(150, self._commit_if_unfocused)

    def _commit_if_unfocused(self):
        if self._suppress_focus_commit or self._popup is not None or not self.winfo_exists():
            return
        self._command(self.get())

    def _clear_focus_commit_suppression(self):
        self._suppress_focus_commit = False

    def _close_popup(self):
        if self._popup is not None:
            popup = self._popup
            self._popup = None
            if popup.winfo_exists():
                popup.destroy()

    def _on_destroy(self, event):
        if event.widget is self:
            self._close_popup()


class TopRoundedTabview(ctk.CTkFrame):
    """
    Folder-style Tabview:
    1. Background behind the tab tails is transparent/window_bg (common gray bar removed).
    2. Each inactive tab is a visible 'tail' with its own dark background (#25272d) and thin gray border (#3c3e47).
    3. The active tab is amber (#ff9900) with black text, top-rounded corners, and thin gray border framing
       its top and sides, opening seamlessly into the content frame below.
    4. Content frame below is framed with the matching thin gray border.
    """
    def __init__(self, master, corner_radius=8, tab_height=36,
                 bg_bar=THEME["header_bg"], window_bg=THEME["bg_main"],
                 border_color=THEME["card_border"], active_bg=THEME["accent_amber"],
                 inactive_bg="#25272d", hover_bg="#32353d",
                 font_family="Segoe UI", font_size=10, **kwargs):
        super().__init__(master, fg_color="transparent", **kwargs)
        self.corner_radius = corner_radius
        self.tab_height = tab_height
        self.bg_bar = bg_bar
        self.window_bg = window_bg
        self.border_color = border_color
        self.active_bg = active_bg
        self.inactive_bg = inactive_bg
        self.hover_bg = hover_bg
        self.font = tkfont.Font(family=font_family, size=font_size)

        self._tabs = []  # list of [id, text]
        self._tab_frames = {}  # id -> CTkFrame
        self._tab_rects = {}  # id -> (x0, x1)
        self._current_tab = None
        self._hovered_tab = None
        self._cached_images = {}

        # Tooltip state
        self._tooltip_timer = None
        self._tooltip_window = None
        self._tooltip_provider = None  # callback(tab_id) -> list of (filename, [(line_text, is_highlighted)])

        # 1. Header Canvas (background is window_bg so only tab tails are visible)
        self.header_canvas = tk.Canvas(
            self, height=self.tab_height, bg=self.window_bg,
            highlightthickness=0, bd=0
        )
        self.header_canvas.pack(fill="x", side="top")

        # 2. Main content container framed with border_color
        self.content_container = ctk.CTkFrame(
            self, corner_radius=self.corner_radius,
            border_width=1, border_color=self.border_color,
            fg_color=self.bg_bar
        )
        self.content_container.pack(fill="both", expand=True, side="top")

        self.header_canvas.bind("<Configure>", lambda e: self._redraw_header())
        self.header_canvas.bind("<Motion>", self._on_motion)
        self.header_canvas.bind("<Leave>", self._on_leave)
        self.header_canvas.bind("<Button-1>", self._on_click)

    def _render_tab_tail(self, w, h, fill_color, border_color, is_active):
        key = (w, h, fill_color, border_color, is_active)
        if key in self._cached_images:
            return self._cached_images[key]
        scale = 4
        W, H_scaled, R = w * scale, h * scale, self.corner_radius * scale
        img = Image.new("RGBA", (W, H_scaled + R), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.rounded_rectangle([0, 0, W - 1, H_scaled + R - 1], radius=R, fill=fill_color, outline=border_color, width=scale)
        if is_active:
            # Erase bottom border so it seamlessly opens into content frame below
            draw.rectangle([scale, H_scaled - 2 * scale, W - 1 - scale, H_scaled + R - 1], fill=fill_color)
        cropped = img.crop((0, 0, W, H_scaled))
        resized = cropped.resize((w, h), Image.Resampling.LANCZOS)
        photo = ImageTk.PhotoImage(resized)
        self._cached_images[key] = photo
        return photo

    def add(self, name: str, title: str = None, visible: bool = True) -> ctk.CTkFrame:
        display_title = title if title is not None else name
        if visible:
            self._tabs.append([name, display_title])
        frame = ctk.CTkFrame(self.content_container, fg_color="transparent")
        self._tab_frames[name] = frame
        if self._current_tab is None:
            self._current_tab = name
            frame.pack(fill="both", expand=True, padx=4, pady=4)
        self._redraw_header()
        return frame

    def set(self, name: str):
        if name in self._tab_frames and self._current_tab != name:
            if self._current_tab and self._current_tab in self._tab_frames:
                self._tab_frames[self._current_tab].pack_forget()
            self._current_tab = name
            self._tab_frames[name].pack(fill="both", expand=True, padx=4, pady=4)
            self._redraw_header()

    def get(self) -> str:
        return self._current_tab or ""

    def set_tab_text(self, tab_id: str, text: str):
        for item in self._tabs:
            if item[0] == tab_id:
                item[1] = text
                break
        self._redraw_header()

    def set_tooltip_provider(self, callback):
        """Set a callback: callback(tab_id) -> list of (filename, [(line_text, is_highlighted)]) or None."""
        self._tooltip_provider = callback

    def _on_motion(self, e):
        x = e.x
        new_hover = None
        for tid, (x0, x1) in self._tab_rects.items():
            if x0 <= x <= x1:
                new_hover = tid
                break
        if new_hover != self._hovered_tab:
            self._hide_tooltip()
            self._hovered_tab = new_hover
            self.header_canvas.configure(cursor="hand2" if new_hover else "")
            self._redraw_header()
            # Start tooltip timer for the new hovered tab
            if new_hover and self._tooltip_provider:
                self._tooltip_timer = self.after(1000, lambda tid=new_hover: self._show_tooltip(tid))

    def _on_leave(self, e):
        self._hide_tooltip()
        if self._hovered_tab is not None:
            self._hovered_tab = None
            self.header_canvas.configure(cursor="")
            self._redraw_header()

    def _hide_tooltip(self):
        if self._tooltip_timer is not None:
            self.after_cancel(self._tooltip_timer)
            self._tooltip_timer = None
        if self._tooltip_window is not None:
            self._tooltip_window.destroy()
            self._tooltip_window = None

    def _show_tooltip(self, tab_id):
        self._tooltip_timer = None
        if self._hovered_tab != tab_id or not self._tooltip_provider:
            return
        snippets = self._tooltip_provider(tab_id)
        if not snippets:
            return

        tw = tk.Toplevel(self)
        tw.wm_overrideredirect(True)
        tw.attributes("-topmost", True)
        tw.configure(bg="#1e1f23")

        # Outer border frame
        border_frame = tk.Frame(tw, bg="#3c3e47", bd=0)
        border_frame.pack(fill="both", expand=True, padx=0, pady=0)
        inner_frame = tk.Frame(border_frame, bg="#1e1f23", bd=0)
        inner_frame.pack(fill="both", expand=True, padx=1, pady=1)

        mono_font = tkfont.Font(family="Consolas", size=9)
        header_font = tkfont.Font(family="Segoe UI", size=9, weight="bold")

        for file_idx, (filename, lines) in enumerate(snippets):
            if file_idx > 0:
                sep = tk.Frame(inner_frame, bg="#3c3e47", height=1)
                sep.pack(fill="x", padx=6, pady=(4, 4))

            # File header
            hdr = tk.Label(
                inner_frame, text=f"📄 {filename}",
                font=header_font, fg="#8ab4f8", bg="#1e1f23",
                anchor="w", padx=8, pady=(4 if file_idx == 0 else 2)
            )
            hdr.pack(fill="x", anchor="w")

            # Code lines
            for line_text, is_highlighted in lines:
                bg = "#3d3520" if is_highlighted else "#1e1f23"
                fg = "#ffd666" if is_highlighted else "#b0b8c8"
                lbl = tk.Label(
                    inner_frame, text=line_text,
                    font=mono_font, fg=fg, bg=bg,
                    anchor="w", padx=10, pady=0
                )
                lbl.pack(fill="x", anchor="w")

        # Add bottom padding
        tk.Frame(inner_frame, bg="#1e1f23", height=4).pack(fill="x")

        tw.update_idletasks()
        tw_w = tw.winfo_reqwidth()
        tw_h = tw.winfo_reqheight()

        # Position below the hovered tab
        tab_rect = self._tab_rects.get(tab_id)
        if tab_rect:
            cx = self.header_canvas.winfo_rootx() + (tab_rect[0] + tab_rect[1]) // 2
            cy = self.header_canvas.winfo_rooty() + self.tab_height + 4
        else:
            cx = self.winfo_rootx() + 50
            cy = self.winfo_rooty() + self.tab_height + 4

        # Keep on screen
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        x = max(4, min(cx - tw_w // 2, screen_w - tw_w - 4))
        y = cy
        if y + tw_h > screen_h - 40:
            y = self.header_canvas.winfo_rooty() - tw_h - 4

        tw.geometry(f"+{x}+{y}")
        self._tooltip_window = tw

        # Auto-hide if mouse moves out
        tw.bind("<Enter>", lambda e: None)
        tw.bind("<Leave>", lambda e: self._hide_tooltip())

    def _on_click(self, e):
        x = e.x
        for tid, (x0, x1) in self._tab_rects.items():
            if x0 <= x <= x1:
                self.set(tid)
                break

    def _redraw_header(self):
        self.header_canvas.delete("all")
        total_w = self.header_canvas.winfo_width()
        if total_w <= 10:
            return

        # 1. Measure and compute tab coordinates
        x_cursor = 8
        self._tab_rects = {}
        for tid, text in self._tabs:
            tw = self.font.measure(text)
            tab_w = tw + 20
            x0 = x_cursor
            x1 = x0 + tab_w
            self._tab_rects[tid] = (x0, x1)
            x_cursor = x1 + 4

        active_rect = self._tab_rects.get(self._current_tab, (0, 0))
        act_x0, act_x1 = active_rect

        # 2. Draw inactive tabs first (individual tails with own visible background and border)
        for tid, text in self._tabs:
            if tid == self._current_tab:
                continue
            x0, x1 = self._tab_rects[tid]
            tab_w = x1 - x0
            is_hovered = (tid == self._hovered_tab)
            bg_col = self.hover_bg if is_hovered else self.inactive_bg
            inact_h = self.tab_height - 2
            img = self._render_tab_tail(tab_w, inact_h, bg_col, self.border_color, False)
            self.header_canvas.create_image(x0, 2, anchor="nw", image=img)
            self.header_canvas.create_text((x0 + x1) // 2, (2 + self.tab_height) // 2, text=text, fill="#dcdcdc", font=self.font)

        # 4. Draw active tab on top (reaching full height, thin border, and breaking the baseline)
        if self._current_tab in self._tab_rects:
            x0, x1 = self._tab_rects[self._current_tab]
            tab_w = x1 - x0
            act_text = ""
            for tid, t in self._tabs:
                if tid == self._current_tab:
                    act_text = t
                    break
            img = self._render_tab_tail(tab_w, self.tab_height, self.active_bg, self.border_color, True)
            self.header_canvas.create_image(x0, 0, anchor="nw", image=img)
            self.header_canvas.create_text((x0 + x1) // 2, self.tab_height // 2, text=act_text, fill="#000000", font=self.font)

        # 5. Clear top border of content container under active tab so they fuse
        try:
            self.content_container._canvas.delete("tab_gap")
            if act_x1 > act_x0:
                self.content_container._canvas.create_line(act_x0, 0, act_x1, 0, fill=self.bg_bar, width=2, tags="tab_gap")
        except Exception:
            pass


class CTkDarkMessageBox(ctk.CTkToplevel):
    """Modern dark theme modal message dialog that seamlessly matches the app's charcoal & amber styling."""
    def __init__(
        self,
        parent,
        title: str,
        message: str,
        dialog_type: str = "info",  # "info", "error", "confirm"
        btn_ok_text: str = "OK",
        btn_yes_text: str = "Да",
        btn_no_text: str = "Отмена",
    ):
        super().__init__(parent)
        self.result = False
        self.title(title)
        self.resizable(False, False)
        self.configure(fg_color=THEME["bg_main"])

        icon_path = Path(__file__).resolve().parent / "app_icon.ico"
        if icon_path.exists():
            self.iconbitmap(str(icon_path))

        self.transient(parent)
        self.grab_set()

        message_font = ctk.CTkFont(size=12)
        num_lines = 0
        for paragraph in message.splitlines() or [""]:
            words = paragraph.split()
            if not words:
                num_lines += 1
                continue
            paragraph_lines = 1
            current_line = words[0]
            for word in words[1:]:
                candidate = f"{current_line} {word}"
                if message_font.measure(candidate) > 400:
                    paragraph_lines += 1
                    current_line = word
                else:
                    current_line = candidate
            num_lines += paragraph_lines

        dw = 460
        dh = max(200, 140 + min(num_lines * 22, 220))

        # Center over parent
        parent.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        x = px + max(0, (pw - dw) // 2)
        y = py + max(0, (ph - dh) // 2)
        self.geometry(f"{dw}x{dh}+{x}+{y}")

        # Main container with card styling matching the app
        main_frame = ctk.CTkFrame(
            self,
            fg_color=THEME["card_bg"],
            corner_radius=12,
            border_width=1,
            border_color=THEME["card_border"]
        )
        main_frame.pack(fill="both", expand=True, padx=12, pady=12)

        # Icon colors (pure glyph, no circle background badge)
        icons = {
            "info": ("✔", "#4ade80"),                  # crisp modern green
            "error": ("✖", "#ef4444"),                 # vibrant red
            "confirm": ("❓", THEME["accent_amber"]),  # amber accent
        }
        icon_char, icon_color = icons.get(dialog_type, ("ℹ", THEME["accent_amber"]))

        # Header with icon & title
        header = ctk.CTkFrame(main_frame, fg_color="transparent")
        header.pack(fill="x", padx=18, pady=(16, 6))

        icon_lbl = ctk.CTkLabel(
            header,
            text=icon_char,
            fg_color="transparent",
            text_color=icon_color,
            font=ctk.CTkFont(size=18, weight="bold")
        )
        icon_lbl.pack(side="left", padx=(0, 10))

        title_lbl = ctk.CTkLabel(
            header,
            text=title,
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["text_primary"]
        )
        title_lbl.pack(side="left")

        # Message body
        msg_lbl = ctk.CTkLabel(
            main_frame,
            text=message,
            font=message_font,
            text_color=THEME["text_primary"],
            wraplength=400,
            justify="left",
            anchor="w"
        )
        msg_lbl.pack(fill="both", expand=True, padx=20, pady=(6, 14))

        # Buttons
        btn_frame = ctk.CTkFrame(main_frame, fg_color="transparent")
        btn_frame.pack(fill="x", padx=18, pady=(0, 16))

        if dialog_type == "confirm":
            def on_yes():
                self.result = True
                self.destroy()

            def on_no():
                self.result = False
                self.destroy()

            cancel_btn = PillButton(
                btn_frame,
                text=btn_no_text,
                width=110,
                height=34,
                corner_radius=17,
                fg_color=THEME["btn_gray"],
                hover_color=THEME["btn_gray_hover"],
                text_color=THEME["text_primary"],
                font=ctk.CTkFont(size=12),
                command=on_no
            )
            cancel_btn.pack(side="right", padx=(10, 0))

            yes_btn = PillButton(
                btn_frame,
                text=btn_yes_text,
                width=110,
                height=34,
                corner_radius=17,
                fg_color=THEME["accent_amber"],
                hover_color=THEME["accent_amber_hover"],
                text_color=THEME["accent_dark_text"],
                font=ctk.CTkFont(size=12, weight="bold"),
                command=on_yes
            )
            yes_btn.pack(side="right")

            self.bind("<Return>", lambda e: on_yes())
            self.bind("<Escape>", lambda e: on_no())
            yes_btn.focus_set()
        else:
            def on_ok():
                self.result = True
                self.destroy()

            ok_btn = PillButton(
                btn_frame,
                text=btn_ok_text,
                width=110,
                height=34,
                corner_radius=17,
                fg_color=THEME["accent_amber"],
                hover_color=THEME["accent_amber_hover"],
                text_color=THEME["accent_dark_text"],
                font=ctk.CTkFont(size=12, weight="bold"),
                command=on_ok
            )
            ok_btn.pack(side="right")

            self.bind("<Return>", lambda e: on_ok())
            self.bind("<Escape>", lambda e: on_ok())
            ok_btn.focus_set()

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _on_close(self):
        self.result = False
        self.destroy()


class CTkAboutDialog(ctk.CTkToplevel):
    """About dialog styled like DCS Translation TOOL with alpha-transparent cat.png in corner."""
    def __init__(self, parent, lang="ru"):
        super().__init__(parent)
        self.title(t("about_title", lang))
        self.geometry("920x520")
        self.resizable(False, False)
        self.configure(fg_color=THEME["bg_main"])
        self.transient(parent)
        self.grab_set()

        # Set window icon
        icon_path = Path(__file__).resolve().parent / "app_icon.ico"
        if icon_path.exists():
            self.iconbitmap(str(icon_path))

        # Center over parent
        parent.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        x = px + max(0, (pw - 920) // 2)
        y = py + max(0, (ph - 520) // 2)
        self.geometry(f"920x520+{x}+{y}")

        # Left container (width 565, contains card and exit button)
        left_container = ctk.CTkFrame(self, width=565, fg_color="transparent")
        left_container.pack(side="left", fill="y", padx=(20, 0), pady=20)
        left_container.pack_propagate(False)

        # Content Card
        content_card = ctk.CTkFrame(
            left_container,
            fg_color=THEME["card_bg"],
            border_color=THEME["card_border"],
            border_width=1,
            corner_radius=10
        )
        content_card.pack(fill="both", expand=True, pady=(0, 14))

        pad = ctk.CTkFrame(content_card, fg_color="transparent")
        pad.pack(fill="both", expand=True, padx=16, pady=16)

        # App title + Version badge
        title_row = ctk.CTkFrame(pad, fg_color="transparent")
        title_row.pack(anchor="w", pady=(0, 4))

        ctk.CTkLabel(
            title_row,
            text="DCS VR UI Configurator",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=THEME["text_title"]
        ).pack(side="left")

        ctk.CTkLabel(
            title_row,
            text=f"v{APP_VERSION} • Portable",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=THEME["accent_amber"],
            fg_color="#2b261b",
            corner_radius=6,
            padx=6,
            pady=1
        ).pack(side="left", padx=(8, 0))

        # Description
        desc_text = (
            f"{t('about_desc_1', lang)}\n"
            f"{t('about_desc_2', lang)}\n"
            f"{t('about_desc_3', lang)}"
        )
        ctk.CTkLabel(
            pad,
            text=desc_text,
            font=ctk.CTkFont(size=12),
            text_color=THEME["text_secondary"],
            justify="left",
            wraplength=540
        ).pack(anchor="w", pady=(0, 10))

        # Links box (dark inset)
        links_box = ctk.CTkFrame(pad, fg_color="#18191c", corner_radius=6, border_width=1, border_color=THEME["card_border"])
        links_box.pack(fill="x", pady=(0, 10))

        # GitHub
        gh_row = ctk.CTkFrame(links_box, fg_color="transparent")
        gh_row.pack(fill="x", padx=10, pady=(8, 4))
        ctk.CTkLabel(gh_row, text="GitHub:", font=ctk.CTkFont(size=11, weight="bold"), text_color=THEME["text_primary"]).pack(side="left")
        gh_link = ctk.CTkLabel(gh_row, text="https://github.com/Hokum-A", font=ctk.CTkFont(size=11, underline=True), text_color=THEME["accent_amber"], cursor="hand2")
        gh_link.pack(side="left", padx=(6, 0))
        gh_link.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/Hokum-A"))

        # Boosty
        bo_row = ctk.CTkFrame(links_box, fg_color="transparent")
        bo_row.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(bo_row, text="Boosty:", font=ctk.CTkFont(size=11, weight="bold"), text_color=THEME["text_primary"]).pack(side="left")
        bo_link = ctk.CTkLabel(bo_row, text="https://boosty.to/hokuma", font=ctk.CTkFont(size=11, underline=True), text_color=THEME["accent_amber"], cursor="hand2")
        bo_link.pack(side="left", padx=(6, 0))
        bo_link.bind("<Button-1>", lambda e: webbrowser.open("https://boosty.to/hokuma"))

        # USDT TRC20 with copy button
        usdt_row = ctk.CTkFrame(links_box, fg_color="transparent")
        usdt_row.pack(fill="x", padx=10, pady=(4, 8))
        ctk.CTkLabel(usdt_row, text="USDT TRC20:", font=ctk.CTkFont(size=11, weight="bold"), text_color=THEME["text_primary"]).pack(side="left")
        ctk.CTkLabel(usdt_row, text="TKLcwmrNmwXFgwbpS66UnAGsB3Lvnqpwv5", font=ctk.CTkFont(family="Consolas", size=10), text_color=THEME["text_secondary"]).pack(side="left", padx=(4, 6))

        lbl_cp_status = ctk.CTkLabel(usdt_row, text="", font=ctk.CTkFont(size=10, weight="bold"), text_color="#4ade80")

        def copy_usdt():
            self.clipboard_clear()
            self.clipboard_append("TKLcwmrNmwXFgwbpS66UnAGsB3Lvnqpwv5")
            btn_cp.configure(text="✔", text_color="#4ade80")
            lbl_cp_status.configure(text=t("about_copied", lang))
            self.after(2000, lambda: (
                btn_cp.configure(text="📋", text_color=THEME["accent_amber"]),
                lbl_cp_status.configure(text="")
            ))

        btn_cp = ctk.CTkButton(
            usdt_row,
            text="📋",
            width=28,
            height=22,
            corner_radius=4,
            fg_color=THEME["btn_gray"],
            hover_color=THEME["btn_gray_hover"],
            text_color=THEME["accent_amber"],
            cursor="hand2",
            command=copy_usdt
        )
        btn_cp.pack(side="left")
        lbl_cp_status.pack(side="left", padx=(6, 0))

        # Author and License
        dev_text = f"{t('about_dev', lang)}\n{t('about_license', lang)}"
        ctk.CTkLabel(
            pad,
            text=dev_text,
            font=ctk.CTkFont(size=12),
            text_color=THEME["text_primary"],
            justify="left"
        ).pack(anchor="w", pady=(0, 6))

        # Thank you note
        ctk.CTkLabel(
            pad,
            text=t("about_thanks", lang),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=THEME["accent_amber"]
        ).pack(anchor="w")

        # White pill exit button centered under content card
        btn_exit = PillButton(
            left_container,
            text=t("btn_back", lang),
            width=130,
            height=34,
            corner_radius=17,
            fg_color="#ffffff",
            hover_color="#e2e8f0",
            text_color="#000000",
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self.destroy
        )
        btn_exit.pack(anchor="center")

        # Cat in bottom-right corner with 100% clean alpha channel
        cat_p = Path(__file__).resolve().parent / "cat.png"
        if cat_p.exists():
            cat_raw = Image.open(cat_p).convert("RGBA")
            cimg = ctk.CTkImage(light_image=cat_raw, dark_image=cat_raw, size=(327, 346))
            self.cat_lbl = ctk.CTkLabel(self, image=cimg, text="", fg_color="transparent")
            self.cat_lbl.place(x=920 - 327, y=520 - 346)

        self.bind("<Escape>", lambda e: self.destroy())


class DcsVrUiEditorApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(f"DCS World VR UI Configurator v{APP_VERSION} • Portable")
        self.configure(fg_color=THEME["bg_main"])

        # Set window icon
        icon_path = Path(__file__).resolve().parent / "app_icon.ico"
        if icon_path.exists():
            self.iconbitmap(str(icon_path))

        # Load persisted settings
        self.app_settings = load_settings()
        self.current_lang = self.app_settings.get("language", "ru")
        self.dcs_path = self.app_settings.get("dcs_path", r"F:\GAMES\DCS World")
        self.saved_games_path = self.app_settings.get("saved_games_path", str(Path.home() / "Saved Games" / "DCS.openbeta"))

        # Keep enough room for the optimization controls and footer without excess space below.
        init_w = max(1200, min(1280, int(self.app_settings.get("window_width", 1280))))
        saved_h = int(self.app_settings.get("window_height", 780))
        init_h = 780 if saved_h == 820 else max(780, saved_h)
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        available_h = max(600, screen_h - 80)
        min_h = min(780, available_h)
        init_h = min(init_h, available_h)
        self.minsize(1200, min_h)

        # Center on screen
        pos_x = max(0, (screen_w - init_w) // 2)
        pos_y = max(0, (screen_h - init_h) // 2)
        self.geometry(f"{init_w}x{init_h}+{pos_x}+{pos_y}")

        # Handle window close to persist dimensions
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Target files dictionary
        self.target_files = get_target_files(self.dcs_path, self.saved_games_path)
        self.route_tool_path = Path(self.dcs_path) / "Scripts" / "UI" / "RouteTool" / "RouteTool.lua"
        from route_tool_manager import ensure_route_tool_original_backup
        ensure_route_tool_original_backup(self.route_tool_path)

        # Ensure factory originals are backed up upon launch
        self.backed_up_files = ensure_clean_backup(self.target_files)
        from scene_vr_manager import ensure_scene_vr_backup
        ensure_scene_vr_backup(self.target_files)

        # State cache
        self.current_live_state = read_current_state(self.target_files)

        # Working state (modified by UI controls)
        self.working_state = self.current_live_state.copy()

        # Track status message for language changes
        self.current_status_key = "status_ready"
        self.current_status_kwargs = {}

        # Build Interface
        self.create_header()
        self.create_tabs()
        self.create_footer()

        # Populate UI with current state and language
        self.sync_ui_from_state(self.working_state)
        self.update_all_translations()

    def show_dark_info(self, title: str, message: str) -> bool:
        dlg = CTkDarkMessageBox(
            self,
            title=title,
            message=message,
            dialog_type="info",
            btn_ok_text=t("dialog_btn_ok", self.current_lang)
        )
        self.wait_window(dlg)
        return True

    def show_dark_error(self, title: str, message: str) -> bool:
        dlg = CTkDarkMessageBox(
            self,
            title=title,
            message=message,
            dialog_type="error",
            btn_ok_text=t("dialog_btn_ok", self.current_lang)
        )
        self.wait_window(dlg)
        return False

    def show_dark_askyesno(self, title: str, message: str) -> bool:
        dlg = CTkDarkMessageBox(
            self,
            title=title,
            message=message,
            dialog_type="confirm",
            btn_yes_text=t("dialog_btn_yes", self.current_lang),
            btn_no_text=t("dialog_btn_cancel", self.current_lang)
        )
        self.wait_window(dlg)
        return dlg.result

    def create_header(self):
        header_frame = ctk.CTkFrame(self, corner_radius=10, fg_color=THEME["header_bg"])
        header_frame.pack(fill="x", padx=15, pady=(10, 4))

        # Title & Subtitle container on left
        title_container = ctk.CTkFrame(header_frame, fg_color="transparent")
        title_container.pack(side="left", padx=15, pady=8)

        # Row 1: [EN] [Toggle] [RU]  +  "DCS VR UI Configurator"
        title_top_row = ctk.CTkFrame(title_container, fg_color="transparent")
        title_top_row.pack(anchor="w", pady=(0, 2))

        # Language Switcher (compact 30x14, directly in line with title, styled like DCS Translation Tool)
        self.lang_frame = ctk.CTkFrame(title_top_row, fg_color="transparent")
        self.lang_frame.pack(side="left", padx=(0, 14), pady=0)

        self.lbl_lang_en = ctk.CTkLabel(
            self.lang_frame,
            text="EN",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color="#ffffff",
            cursor="hand2"
        )
        self.lbl_lang_en.pack(side="left", padx=(0, 4))
        self.lbl_lang_en.bind("<Button-1>", lambda e: self.sw_lang.set_checked(False))

        self.sw_lang = LanguageToggleSwitch(
            self.lang_frame,
            bg_color=THEME["header_bg"],
            initial_lang=self.current_lang,
            command=self.set_language
        )
        self.sw_lang.pack(side="left", padx=0)

        self.lbl_lang_ru = ctk.CTkLabel(
            self.lang_frame,
            text="RU",
            font=ctk.CTkFont(size=9, weight="bold"),
            text_color="#ffffff",
            cursor="hand2"
        )
        self.lbl_lang_ru.pack(side="left", padx=(4, 0))
        self.lbl_lang_ru.bind("<Button-1>", lambda e: self.sw_lang.set_checked(True))

        # Title on the same line
        self.lbl_app_title = ctk.CTkLabel(
            title_top_row,
            text=t("app_title", self.current_lang),
            font=ctk.CTkFont(size=19, weight="bold"),
            text_color=THEME["text_title"]
        )
        self.lbl_app_title.pack(side="left", anchor="center")

        # Version badge
        self.lbl_version_badge = ctk.CTkLabel(
            title_top_row,
            text=f"v{APP_VERSION}",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=THEME["accent_amber"],
            fg_color="#2b261b",
            corner_radius=6,
            padx=7,
            pady=1,
            cursor="hand2"
        )
        self.lbl_version_badge.pack(side="left", padx=(8, 0), anchor="center")
        self.lbl_version_badge.bind("<Button-1>", lambda e: self.open_about_dialog())

        # Subtitle on the line below, flush to the left of title_container
        self.lbl_app_sub = ctk.CTkLabel(
            title_container,
            text=t("app_subtitle", self.current_lang),
            font=ctk.CTkFont(size=12),
            text_color=THEME["text_secondary"]
        )
        self.lbl_app_sub.pack(anchor="w", pady=(0, 0))

        # Badges box on top-right (Single horizontal row, transparent background)
        badges_box = ctk.CTkFrame(header_frame, fg_color="transparent")
        badges_box.pack(side="right", padx=15, pady=(12, 8), anchor="ne")

        self.dcs_status_badge = ctk.CTkLabel(
            badges_box,
            text=t("status_dcs_found", self.current_lang),
            fg_color="transparent",
            text_color=THEME["status_green_text"],
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.dcs_status_badge.pack(side="left", padx=(0, 14))

        self.backup_status_badge = ctk.CTkLabel(
            badges_box,
            text=t("status_backup_safe", self.current_lang),
            fg_color="transparent",
            text_color=THEME["status_green_text"],
            font=ctk.CTkFont(size=12, weight="bold")
        )
        self.backup_status_badge.pack(side="left")

        # About button in header (circular 'i' button)
        self.btn_about = PillButton(
            badges_box,
            text="i",
            width=28,
            height=28,
            corner_radius=14,
            fg_color=THEME["btn_gray"],
            hover_color=THEME["btn_gray_hover"],
            text_color=THEME["text_primary"],
            font=ctk.CTkFont(family="Segoe UI", size=13, weight="bold"),
            command=self.open_about_dialog
        )
        self.btn_about.pack(side="left", padx=(14, 0))

    def open_about_dialog(self):
        dlg = CTkAboutDialog(self, lang=self.current_lang)
        self.wait_window(dlg)

    def set_language(self, lang: str):
        if self.current_lang != lang:
            self.current_lang = lang
            self.app_settings["language"] = lang
            save_settings(self.app_settings)
            if self.sw_lang.is_checked() != (lang == "ru"):
                self.sw_lang.set_checked(lang == "ru", animate=False)

            self.update_all_translations()

    def create_tabs(self):
        self.tabview = TopRoundedTabview(
            self,
            corner_radius=8,
            tab_height=36,
            bg_bar=THEME["header_bg"],
            window_bg=THEME["bg_main"],
            active_bg=THEME["accent_amber"]
        )
        self.tabview.pack(fill="both", expand=True, padx=15, pady=(0, 6))

        # Internal tab keys (fixed identifiers) with localized title
        self.tab_presets = self.tabview.add("presets", t("tab_presets", self.current_lang))
        self.tab_messages = self.tabview.add("messages", t("tab_messages", self.current_lang))
        self.tab_radio = self.tabview.add("radio", t("tab_radio", self.current_lang))
        # Keep the options implementation available for future work, but hide this tab
        # while its current controls are under evaluation.
        self.tab_options = self.tabview.add("options", t("tab_options", self.current_lang), visible=False)
        self.tab_tweaks = self.tabview.add("tweaks", t("tab_tweaks", self.current_lang))
        self.tab_backups = self.tabview.add("backups", t("tab_backups", self.current_lang))

        self.tabview.set("presets")

        self.build_presets_tab()
        self.build_messages_tab()
        self.build_radio_tab()
        self.build_options_tab()
        self.build_tweaks_tab()
        self.build_backups_tab()

        # Hook up code preview tooltips for file-editing tabs
        self.tabview.set_tooltip_provider(self._get_tab_code_preview)

    def _get_tab_code_preview(self, tab_id):
        """Return list of (filename, [(line_text, is_highlighted)]) for the given tab."""
        import re

        def _extract_snippet(filepath, patterns, context=2):
            """Read a file and extract lines matching any of the given regex patterns,
            with `context` lines above/below each match. Returns [(line_text, is_highlighted)]."""
            try:
                content = filepath.read_text(encoding="utf-8")
            except Exception:
                return None  # file read error
            lines = content.splitlines()
            # Find matching line numbers
            matched = set()
            for pat in patterns:
                for i, line in enumerate(lines):
                    if re.search(pat, line):
                        matched.add(i)
            if not matched:
                return []
            # Build snippet ranges (merge overlapping)
            ranges = []
            for m in sorted(matched):
                lo = max(0, m - context)
                hi = min(len(lines) - 1, m + context)
                if ranges and lo <= ranges[-1][1] + 2:
                    ranges[-1] = (ranges[-1][0], hi)
                else:
                    ranges.append((lo, hi))
            result = []
            for rng_idx, (lo, hi) in enumerate(ranges):
                if rng_idx > 0:
                    result.append(("    ···", False))
                for i in range(lo, hi + 1):
                    prefix = f"  {i + 1:>4}  "
                    result.append((prefix + lines[i], i in matched))
            return result

        if tab_id == "messages":
            snippets = []
            # gameMessages.lua
            gm_path = self.target_files.get("gameMessages_lua")
            if gm_path and gm_path.exists():
                lines_data = _extract_snippet(gm_path, [
                    r"if\s+HMD\.isActive\(\)\s+then",
                    r"width\s*=\s*(main_w\s*/|[\d]+)",
                ])
                if lines_data is not None:
                    snippets.append(("gameMessages.lua", lines_data))
            else:
                snippets.append(("gameMessages.lua", [("  ⚠ Файл не найден", False)]))
            # gameMessages.dlg
            dlg_path = self.target_files.get("gameMessages_dlg")
            if dlg_path and dlg_path.exists():
                lines_data = _extract_snippet(dlg_path, [
                    r'\["fontSize"\]\s*=\s*\d+',
                ], context=1)
                if lines_data is not None:
                    # Limit to first 10 lines to keep tooltip compact
                    snippets.append(("gameMessages.dlg", lines_data[:12]))
            else:
                snippets.append(("gameMessages.dlg", [("  ⚠ Файл не найден", False)]))
            return snippets if snippets else None

        elif tab_id == "radio":
            cm_path = self.target_files.get("CommandMenu_lua")
            if cm_path and cm_path.exists():
                lines_data = _extract_snippet(cm_path, [
                    r"if\s+HMD\.isActive\(\)\s+then",
                    r"fontScale\s*=\s*fontScale\s*\*",
                    r"return\s+\d+\s*\*\s*fontScale",
                ])
                if lines_data is not None:
                    return [("CommandMenu.lua", lines_data)]
            return [("CommandMenu.lua", [("  ⚠ Файл не найден", False)])]

        elif tab_id == "options":
            opt_path = self.target_files.get("options_lua")
            if opt_path and opt_path.exists():
                lines_data = _extract_snippet(opt_path, [
                    r'\["messagesFontScale"\]',
                    r'\["custom_IPD"\]',
                    r'\["box_mouse_cursor"\]',
                ])
                if lines_data is not None:
                    return [("options.lua", lines_data)]
            return [("options.lua", [("  ⚠ Файл не найден", False)])]

        # presets, tweaks, backups — no tooltip
        return None

    # ---------------- TAB 1: PRESETS (No Scrollbar) ----------------
    def build_presets_tab(self):
        container = ctk.CTkFrame(self.tab_presets, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=6)

        info_box = ctk.CTkFrame(
            container, fg_color=THEME["sub_box_bg"], corner_radius=8,
            border_width=1, border_color="#454854"
        )
        info_box.pack(fill="x", pady=(0, 6), padx=4)

        self.lbl_presets_info = ctk.CTkLabel(
            info_box, text=t("presets_info", self.current_lang), font=ctk.CTkFont(size=12),
            text_color=THEME["accent_gold"], justify="left"
        )
        self.lbl_presets_info.pack(anchor="w", padx=16, pady=8)

        # Preset Cards (4 standard presets + 1 custom profile)
        self.preset_widgets = {}

        all_keys = list(PRESETS.keys()) + ["custom"]
        for key in all_keys:
            card = ctk.CTkFrame(
                container, corner_radius=8, fg_color=THEME["card_bg"],
                border_width=1, border_color=THEME["card_border"]
            )
            card.pack(fill="x", pady=3, padx=4)

            # Right action container
            right_box = ctk.CTkFrame(card, fg_color="transparent")
            right_box.pack(side="right", padx=(8, 14), pady=8)

            badge_active = ctk.CTkLabel(
                right_box,
                text=t("badge_active_dcs", self.current_lang),
                font=ctk.CTkFont(size=13, weight="bold"),
                text_color="#4ade80"
            )

            if key == "custom":
                self.lbl_custom_match = ctk.CTkLabel(
                    right_box,
                    text="",
                    font=ctk.CTkFont(size=12),
                    text_color=THEME["text_secondary"]
                )
                btn = PillButton(
                    right_box,
                    text=t("btn_load_custom", self.current_lang),
                    width=175,
                    height=34,
                    corner_radius=17,
                    fg_color=THEME["accent_amber"],
                    hover_color=THEME["accent_amber_hover"],
                    text_color=THEME["accent_dark_text"],
                    font=ctk.CTkFont(size=12),
                    command=self.select_custom_profile
                )
            else:
                btn = PillButton(
                    right_box,
                    text=t("btn_select_preset", self.current_lang),
                    width=140,
                    height=34,
                    corner_radius=17,
                    fg_color=THEME["accent_amber"],
                    hover_color=THEME["accent_amber_hover"],
                    text_color=THEME["accent_dark_text"],
                    font=ctk.CTkFont(size=12),
                    command=lambda k=key: self.select_preset(k)
                )

            # Left content container
            left_box = ctk.CTkFrame(card, fg_color="transparent")
            left_box.pack(side="left", fill="both", expand=True, padx=(14, 8), pady=8)

            title_text = get_preset_title(key, self.current_lang) if key != "custom" else t("preset_custom_title", self.current_lang)
            title_lbl = ctk.CTkLabel(
                left_box, text=title_text,
                font=ctk.CTkFont(size=14, weight="bold"),
                text_color=THEME["text_primary"]
            )
            title_lbl.pack(anchor="w")

            desc_text = get_preset_desc(key, self.current_lang) if key != "custom" else t("preset_custom_desc_empty", self.current_lang)
            desc_lbl = ctk.CTkLabel(
                left_box, text=desc_text,
                font=ctk.CTkFont(size=12),
                text_color=THEME["text_secondary"], justify="left", wraplength=700
            )
            desc_lbl.pack(anchor="w", pady=(3, 0))

            self.preset_widgets[key] = {
                "card": card,
                "title": title_lbl,
                "desc": desc_lbl,
                "btn": btn,
                "badge_active": badge_active,
                "right_box": right_box
            }

        self.update_presets_tab_display()

    def select_preset(self, preset_key: str):
        """Applies preset immediately to DCS files, updates sliders so user can tweak from here, but DOES NOT touch custom profile."""
        if preset_key not in PRESETS:
            return
        p_settings = PRESETS[preset_key]["settings"]

        ready, error = self._preflight_builtin_options()
        if not ready:
            self.show_dark_error(
                t("dialog_error_title", self.current_lang),
                t("builtin_preset_originals_error", self.current_lang, error=error)
            )
            return

        option_files, option_errors = self._restore_builtin_options()
        if option_errors:
            if option_files:
                self._sync_builtin_option_ui()
            error_text = "\n".join(f"• {error}" for error in option_errors)
            self.show_dark_error(
                t("dialog_error_title", self.current_lang),
                t("dialog_error_apply", self.current_lang, errors=error_text)
            )
            return

        # 1. Write preset settings to DCS files
        success, updated_files, errors = apply_settings(self.target_files, p_settings)
        updated_files.extend(option_files)
        self._sync_builtin_option_ui()

        # 3. Update working_state AND sync sliders so user sees values to tweak from
        self.working_state.update(p_settings)
        self.sync_ui_from_state(self.working_state)

        # 4. Refresh live state from disk
        self.current_live_state = read_current_state(self.target_files)

        # 5. Track active preset for 1-click apply; DO NOT touch saved_custom_profile!
        self.app_settings["active_preset"] = preset_key
        save_settings(self.app_settings)

        self.update_status_by_key("status_ready")
        self.update_presets_tab_display()

        title = get_preset_title(preset_key, self.current_lang)
        if success:
            if updated_files:
                files_str = "\n".join(f"• {f}" for f in updated_files)
                msg = t("dialog_saved_msg", self.current_lang, count=len(updated_files), files=files_str)
            else:
                msg = t("preset_applied_no_changes", self.current_lang, title=title)
            self.show_dark_info(t("dialog_success_title", self.current_lang), msg)
        else:
            err_str = "\n".join(f"• {e}" for e in errors)
            msg = t("dialog_error_apply", self.current_lang, errors=err_str)
            self.show_dark_error(t("dialog_error_title", self.current_lang), msg)

    def select_custom_profile(self):
        """Applies saved custom profile immediately to DCS files and updates sliders."""
        saved = self.app_settings.get("saved_custom_profile", {})
        if not saved:
            self.show_dark_info(
                t("dialog_no_custom_title", self.current_lang),
                t("dialog_no_custom_msg", self.current_lang)
            )
            return

        # 1. Write saved custom profile to DCS files
        success, updated_files, errors = apply_settings(self.target_files, saved)
        option_files, option_errors = self.apply_custom_profile_options(saved)
        updated_files.extend(option_files)
        errors.extend(option_errors)

        # 3. Update working_state and sync sliders
        self.working_state.update(saved)
        self.sync_ui_from_state(self.working_state)

        # 4. Refresh live state
        self.current_live_state = read_current_state(self.target_files)

        # 5. Track active preset as custom
        self.app_settings["active_preset"] = "custom"
        save_settings(self.app_settings)

        self.update_status_by_key("status_ready")
        self.update_presets_tab_display()

        if success:
            if errors:
                err_str = "\n".join(f"• {error}" for error in errors)
                msg = t("dialog_error_apply", self.current_lang, errors=err_str)
                self.show_dark_error(t("dialog_error_title", self.current_lang), msg)
            elif updated_files:
                files_str = "\n".join(f"• {f}" for f in updated_files)
                msg = t("dialog_saved_msg", self.current_lang, count=len(updated_files), files=files_str)
                self.show_dark_info(t("dialog_success_title", self.current_lang), msg)
            else:
                self.show_dark_info(
                    t("dialog_success_title", self.current_lang),
                    t("preset_loaded_custom_no_changes", self.current_lang)
                )
        else:
            err_str = "\n".join(f"• {e}" for e in errors)
            msg = t("dialog_error_apply", self.current_lang, errors=err_str)
            self.show_dark_error(t("dialog_error_title", self.current_lang), msg)

    def _preflight_builtin_options(self):
        """Verify preserved originals and readable targets before changing any preset files."""
        from scene_vr_manager import (
            ensure_scene_vr_backup,
            get_original_scene_vr_file,
            get_scene_vr_file,
            has_valid_original_scene_vr_backup,
        )
        from route_tool_manager import (
            RouteToolError,
            read_original_route_tool_defaults,
            read_route_tool_defaults,
        )

        scene_path = get_scene_vr_file(self.target_files)
        original_scene_path = get_original_scene_vr_file(self.target_files)
        if not scene_path or not scene_path.is_file():
            return False, t("builtin_preset_scene_target_missing", self.current_lang)
        ensure_scene_vr_backup(self.target_files)
        if not original_scene_path or not original_scene_path.is_file():
            return False, t("builtin_preset_scene_backup_missing", self.current_lang)
        try:
            scene_path.read_bytes()
            original_scene_path.read_bytes()
            if not has_valid_original_scene_vr_backup(self.target_files):
                return False, t("builtin_preset_scene_backup_invalid", self.current_lang)
            read_route_tool_defaults(self.route_tool_path)
            read_original_route_tool_defaults(self.route_tool_path)
        except RouteToolError:
            return False, t("builtin_preset_route_backup_invalid", self.current_lang)
        except (OSError, ValueError):
            return False, t("builtin_preset_files_unreadable", self.current_lang)
        return True, ""

    def _restore_builtin_options(self):
        """Restore preserved SceneVR and waypoint defaults for a built-in preset."""
        from scene_vr_manager import (
            get_original_scene_vr_file,
            get_scene_vr_file,
            restore_scene_vr_original,
        )
        from route_tool_manager import RouteToolError, restore_route_tool_original

        updated_files = []
        errors = []
        try:
            scene_path = get_scene_vr_file(self.target_files)
            original_scene_path = get_original_scene_vr_file(self.target_files)
            scene_changed = (
                scene_path.read_bytes() != original_scene_path.read_bytes()
            )
            if restore_route_tool_original(self.route_tool_path):
                updated_files.append("RouteTool.lua")
            success, error = restore_scene_vr_original(self.target_files)
            if not success:
                errors.append(error)
            elif scene_changed:
                updated_files.append("SceneVR.lua")
        except (OSError, ValueError, RouteToolError) as error:
            errors.append(str(error))
        return updated_files, errors

    def _sync_builtin_option_ui(self):
        from scene_vr_manager import detect_scene_vr_mode

        if hasattr(self, "var_scene_mode"):
            self.var_scene_mode.set(detect_scene_vr_mode(self.target_files))
            self.refresh_scene_original_control()
            self.update_scene_vr_badge()
        if hasattr(self, "switch_route_tool"):
            self.refresh_route_tool_control()
        self.current_live_state = read_current_state(self.target_files)
        self.update_presets_tab_display()

    def refresh_scene_original_control(self):
        from scene_vr_manager import has_valid_original_scene_vr_backup

        if not hasattr(self, "rb_scene_orig"):
            return
        available = has_valid_original_scene_vr_backup(self.target_files)
        self.rb_scene_orig.configure(state="normal" if available else "disabled")
        if hasattr(self, "lbl_scene_original_warning"):
            if available:
                self.lbl_scene_original_warning.pack_forget()
            else:
                self.lbl_scene_original_warning.configure(
                    text=t("scene_original_backup_unavailable", self.current_lang)
                )
                self.lbl_scene_original_warning.pack(
                    anchor="w",
                    padx=(52, 12),
                    pady=(0, 8)
                )

    def _scene_matches_original(self):
        from scene_vr_manager import get_original_scene_vr_file, get_scene_vr_file

        scene_path = get_scene_vr_file(self.target_files)
        original_scene_path = get_original_scene_vr_file(self.target_files)
        try:
            return bool(
                scene_path
                and original_scene_path
                and scene_path.read_bytes() == original_scene_path.read_bytes()
            )
        except OSError:
            return False

    def _builtin_options_match_live(self):
        """Return True/False when classifiable, otherwise None."""
        from scene_vr_manager import (
            MODE_BLACK,
            MODE_ORIGINAL,
            MODE_SKY,
            detect_scene_vr_mode,
            has_valid_original_scene_vr_backup,
        )
        from route_tool_manager import (
            RouteToolError,
            read_original_route_tool_defaults,
            read_route_tool_defaults,
        )

        try:
            scene_mode = detect_scene_vr_mode(self.target_files)
            if scene_mode in (MODE_SKY, MODE_BLACK):
                return False
            if scene_mode != MODE_ORIGINAL or not has_valid_original_scene_vr_backup(self.target_files):
                return None
            scene_matches_original = self._scene_matches_original()
            if not scene_matches_original:
                return False
            return (
                read_route_tool_defaults(self.route_tool_path)
                == read_original_route_tool_defaults(self.route_tool_path)
            )
        except (OSError, ValueError, RouteToolError):
            return None

    @staticmethod
    def _profile_matches_builtin_options(profile):
        from scene_vr_manager import MODE_ORIGINAL

        return (
            profile.get("scene_vr_mode") == MODE_ORIGINAL
            and profile.get("route_tool_enabled") is False
        )

    def apply_custom_profile_options(self, profile):
        """Applies saved optimization settings without changing autoexec.cfg."""
        updated_files = []
        errors = []

        if "scene_vr_mode" in profile:
            from scene_vr_manager import (
                MODE_BLACK,
                MODE_ORIGINAL,
                MODE_SKY,
                apply_scene_vr_mode,
                detect_scene_vr_mode,
                has_valid_original_scene_vr_backup,
            )

            mode = profile["scene_vr_mode"]
            if mode not in (MODE_ORIGINAL, MODE_SKY, MODE_BLACK):
                errors.append(t("custom_profile_invalid_scene"))
            else:
                previous_mode = detect_scene_vr_mode(self.target_files)
                if mode == MODE_ORIGINAL:
                    from scene_vr_manager import (
                        get_original_scene_vr_file,
                        get_scene_vr_file,
                        restore_scene_vr_original,
                    )
                    scene_path = get_scene_vr_file(self.target_files)
                    original_scene_path = get_original_scene_vr_file(self.target_files)
                    if not has_valid_original_scene_vr_backup(self.target_files):
                        success = False
                        error = t("custom_profile_scene_original_unavailable", self.current_lang)
                        scene_changed = False
                    else:
                        try:
                            previous_content = scene_path.read_bytes() if scene_path else None
                            original_content = original_scene_path.read_bytes()
                            success, error = restore_scene_vr_original(self.target_files)
                            scene_changed = success and previous_content != original_content
                        except OSError as read_error:
                            success, error = False, str(read_error)
                            scene_changed = False
                else:
                    success, error = apply_scene_vr_mode(self.target_files, mode)
                    scene_changed = previous_mode != mode
                if success:
                    self.var_scene_mode.set(mode)
                else:
                    self.var_scene_mode.set(detect_scene_vr_mode(self.target_files))
                    errors.append(t("custom_profile_scene_error", error=error))
                self.refresh_scene_original_control()
                self.update_scene_vr_badge()
                if success:
                    if scene_changed:
                        updated_files.append("SceneVR.lua")

        if "route_tool_enabled" in profile:
            from route_tool_manager import RouteToolError, set_route_tool_enabled

            enabled = profile["route_tool_enabled"]
            if not isinstance(enabled, bool):
                errors.append(t("custom_profile_invalid_route"))
            else:
                try:
                    if set_route_tool_enabled(self.route_tool_path, enabled):
                        updated_files.append("RouteTool.lua")
                    self.var_route_tool_enabled.set(enabled)
                    self.refresh_route_tool_control()
                except (OSError, RouteToolError) as error:
                    self.refresh_route_tool_control()
                    errors.append(t("custom_profile_route_error", error=str(error)))

        return updated_files, errors

    def action_save_custom_profile(self):
        """Saves current working_state into saved_custom_profile.
        If current active profile is custom, also applies to DCS files.
        Otherwise, only saves profile without modifying DCS files."""
        saved_profile = self.working_state.copy()
        saved_profile["scene_vr_mode"] = self.var_scene_mode.get()
        saved_profile["route_tool_enabled"] = bool(self.var_route_tool_enabled.get())
        self.app_settings["saved_custom_profile"] = saved_profile

        # Check which profile is physically active on disk
        live_options_match_builtin = self._builtin_options_match_live()
        live_key = None
        if live_options_match_builtin is False:
            live_key = "custom"
        elif live_options_match_builtin is True:
            live_key = "custom"
            for k, pdata in PRESETS.items():
                if matches_settings(self.current_live_state, pdata["settings"]):
                    live_key = k
                    break

        is_custom_active = (self.app_settings.get("active_preset") == "custom" or live_key == "custom")

        if is_custom_active:
            # Active profile is user's custom profile -> apply changes to DCS files immediately
            self.app_settings["active_preset"] = "custom"
            save_settings(self.app_settings)
            success, updated_files, errors = apply_settings(self.target_files, self.working_state)
            option_files, option_errors = self.apply_custom_profile_options(saved_profile)
            updated_files.extend(option_files)
            errors.extend(option_errors)
            if success:
                self.current_live_state = read_current_state(self.target_files)
                self.update_status_by_key("status_ready")
                self.update_presets_tab_display()
                if errors:
                    err_str = "\n".join(f"• {error}" for error in errors)
                    msg = t("dialog_error_apply", self.current_lang, errors=err_str)
                    self.show_dark_error(t("dialog_error_title", self.current_lang), msg)
                elif updated_files:
                    files_str = "\n".join(f"• {f}" for f in updated_files)
                    msg = t("dialog_saved_msg", self.current_lang, count=len(updated_files), files=files_str)
                    self.show_dark_info(t("dialog_success_title", self.current_lang), msg)
                else:
                    self.show_dark_info(
                        t("dialog_success_title", self.current_lang),
                        t("dialog_saved_unchanged", self.current_lang)
                    )
            else:
                err_str = "\n".join(f"• {e}" for e in errors)
                msg = t("dialog_error_apply", self.current_lang, errors=err_str)
                self.show_dark_error(t("dialog_error_title", self.current_lang), msg)
        else:
            # Active profile is a standard preset -> do not modify DCS files
            save_settings(self.app_settings)
            self.update_status_by_key("custom_saved_status")
            self.update_presets_tab_display()
            self.show_dark_info(t("dialog_success_title", self.current_lang), t("dialog_custom_saved_only", self.current_lang))

    def update_presets_tab_display(self):
        """Updates borders, buttons and active/ready badges across all 5 preset cards."""
        if not hasattr(self, "preset_widgets") or not self.preset_widgets:
            return

        # 1. Determine which card matches files physically on disk (current_live_state)
        live_options_match_builtin = self._builtin_options_match_live()
        live_key = None
        if live_options_match_builtin is False:
            live_key = "custom"
        elif live_options_match_builtin is True:
            live_key = "custom"
            for k, pdata in PRESETS.items():
                if matches_settings(self.current_live_state, pdata["settings"]):
                    live_key = k
                    break

        # 2. Determine which card matches working_state (currently in editor sliders)
        working_key = "custom"
        working_options_are_original = (
            not hasattr(self, "var_scene_mode")
            or self.var_scene_mode.get() == "original"
        ) and (
            not hasattr(self, "var_route_tool_enabled")
            or not bool(self.var_route_tool_enabled.get())
        )
        if working_options_are_original:
            for k, pdata in PRESETS.items():
                if matches_settings(self.working_state, pdata["settings"]):
                    working_key = k
                    break

        # Update detailed description for custom card with current saved settings
        saved_profile = self.app_settings.get("saved_custom_profile", {})
        has_saved_profile = bool(saved_profile)
        is_live_matching_saved = has_saved_profile and matches_settings(self.current_live_state, saved_profile)
        if is_live_matching_saved and "scene_vr_mode" in saved_profile:
            from scene_vr_manager import detect_scene_vr_mode
            if saved_profile["scene_vr_mode"] == "original":
                is_live_matching_saved = self._scene_matches_original()
            else:
                is_live_matching_saved = (
                    detect_scene_vr_mode(self.target_files) == saved_profile["scene_vr_mode"]
                )
        elif is_live_matching_saved:
            is_live_matching_saved = False
        if is_live_matching_saved and "route_tool_enabled" in saved_profile:
            from route_tool_manager import is_route_tool_enabled, read_route_tool_defaults
            try:
                current_route_setting = is_route_tool_enabled(
                    read_route_tool_defaults(self.route_tool_path)
                )
                is_live_matching_saved = current_route_setting == saved_profile["route_tool_enabled"]
            except (OSError, ValueError):
                is_live_matching_saved = False
        elif is_live_matching_saved:
            is_live_matching_saved = False
        if live_key is None and is_live_matching_saved:
            live_key = "custom"

        if "custom" in self.preset_widgets:
            if has_saved_profile:
                summary = format_profile_detailed(saved_profile, self.current_lang)
                if live_key == "custom" and not is_live_matching_saved:
                    diff_note = (
                        "\n\n⚠ В файлах DCS активны другие ручные настройки, отличающиеся от сохранённого профиля."
                        if self.current_lang == "ru"
                        else "\n\n⚠ Different custom settings are currently active in DCS files."
                    )
                    summary += diff_note
            else:
                if live_key == "custom":
                    live_summary = format_profile_detailed(self.current_live_state, self.current_lang)
                    if live_summary:
                        summary = live_summary + "\n\n💡 " + t("preset_custom_desc_active_unsaved", self.current_lang)
                    else:
                        summary = t("preset_custom_desc_empty", self.current_lang)
                else:
                    summary = t("preset_custom_desc_empty", self.current_lang)
            self.preset_widgets["custom"]["desc"].configure(text=summary)

        # Check if saved_custom_profile matches any standard preset
        matching_preset_key = None
        if saved_profile:
            if self._profile_matches_builtin_options(saved_profile):
                for pk, pdata in PRESETS.items():
                    if matches_settings(saved_profile, pdata["settings"]):
                        matching_preset_key = pk
                        break

        if hasattr(self, "lbl_custom_match"):
            self.lbl_custom_match.pack_forget()

        # Update each card's visuals
        all_keys = list(PRESETS.keys()) + ["custom"]
        for k in all_keys:
            w = self.preset_widgets.get(k)
            if not w:
                continue

            card = w["card"]
            btn = w["btn"]
            badge_active = w["badge_active"]

            # Border: yellow for working_key (currently loaded in editor), gray for others
            if k == working_key:
                card.configure(border_color=THEME["accent_amber"], border_width=2)
            else:
                card.configure(border_color=THEME["card_border"], border_width=1)

            # Clear right_box pack
            badge_active.pack_forget()
            btn.pack_forget()

            # Right box logic:
            if k == "custom":
                if matching_preset_key:
                    p_title = get_preset_title(matching_preset_key, self.current_lang)
                    short_title = p_title.split("(")[0].strip()
                    match_text = t("custom_matches_preset", self.current_lang, name=short_title)
                    self.lbl_custom_match.configure(text=match_text)
                    self.lbl_custom_match.pack(side="left", padx=(0, 10))
                    if k == live_key:
                        badge_text = (
                            "badge_active_dcs"
                            if is_live_matching_saved
                            else "badge_active_dcs_unsaved"
                        )
                        badge_active.configure(text=t(badge_text, self.current_lang))
                        badge_active.pack(side="right", padx=(0, 6))
                    btn.pack(side="right")
                elif k == live_key:
                    if is_live_matching_saved:
                        badge_active.configure(text=t("badge_active_dcs", self.current_lang))
                        badge_active.pack(side="right", padx=(0, 6))
                    else:
                        badge_active.configure(text=t("badge_active_dcs_unsaved", self.current_lang))
                        badge_active.pack(side="right", padx=(0, 6))
                        btn.pack(side="right")
                else:
                    btn.pack(side="right")
            else:
                if k == live_key:
                    badge_active.configure(text=t("badge_active_dcs", self.current_lang))
                    badge_active.pack(side="right", padx=(0, 6))
                else:
                    btn.pack(side="right")

    # ---------------- TAB 2: MESSAGES (No Scrollbar) ----------------
    def build_messages_tab(self):
        container = ctk.CTkFrame(self.tab_messages, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=6)

        # 1. Width Mode Selection Card
        w_card = ctk.CTkFrame(container, corner_radius=8, fg_color=THEME["card_bg"], border_width=1, border_color=THEME["card_border"])
        w_card.pack(fill="x", pady=6, padx=4)

        self.lbl_msg_c1_title = ctk.CTkLabel(w_card, text=t("msg_card1_title", self.current_lang), font=ctk.CTkFont(size=14, weight="bold"), text_color=THEME["accent_gold"])
        self.lbl_msg_c1_title.pack(anchor="w", padx=15, pady=(10, 2))
        
        self.lbl_msg_c1_desc = ctk.CTkLabel(
            w_card,
            text=t("msg_card1_desc", self.current_lang),
            font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"], justify="left"
        )
        self.lbl_msg_c1_desc.pack(anchor="w", padx=15, pady=(0, 8))

        # Radio mode selector
        self.var_width_mode = tk.StringVar(value="fraction")
        mode_box = ctk.CTkFrame(w_card, fg_color="transparent")
        mode_box.pack(anchor="w", padx=15, pady=(0, 8))

        self.r_frac = PremiumRadioButton(
            mode_box, text=t("mode_fraction", self.current_lang), variable=self.var_width_mode,
            value="fraction", command=self.on_width_mode_changed,
            fg_color=THEME["accent_amber"], hover_color=THEME["accent_amber_hover"]
        )
        self.r_frac.pack(side="left", padx=(0, 20))

        self.r_fixed = PremiumRadioButton(
            mode_box, text=t("mode_fixed", self.current_lang), variable=self.var_width_mode,
            value="fixed", command=self.on_width_mode_changed,
            fg_color=THEME["accent_amber"], hover_color=THEME["accent_amber_hover"]
        )
        self.r_fixed.pack(side="left")

        # Sub-frame for Fraction
        self.frame_fraction = ctk.CTkFrame(w_card, fg_color=THEME["sub_box_bg"], corner_radius=6)
        self.frame_fraction.pack(fill="x", padx=15, pady=(0, 10))

        self.lbl_frac_select = ctk.CTkLabel(self.frame_fraction, text=t("fraction_label", self.current_lang), font=ctk.CTkFont(size=12))
        self.lbl_frac_select.pack(side="left", padx=12, pady=6)
        
        self.seg_fraction = ctk.CTkSegmentedButton(
            self.frame_fraction,
            values=[
                t("frac_1_2", self.current_lang),
                t("frac_1_3", self.current_lang),
                t("frac_1_4", self.current_lang),
                t("frac_1_5", self.current_lang)
            ],
            command=self.on_fraction_segment_changed,
            selected_color=THEME["accent_amber"],
            selected_hover_color=THEME["accent_amber_hover"],
            unselected_color=THEME["card_bg"],
            unselected_hover_color=THEME["btn_gray"]
        )

        # Hook selection so the active yellow/amber button has black text (#000000)
        orig_frac_select = self.seg_fraction._select_button_by_value
        orig_frac_unselect = self.seg_fraction._unselect_button_by_value

        def custom_frac_select(val):
            orig_frac_select(val)
            for v, b in self.seg_fraction._buttons_dict.items():
                if v == val:
                    b.configure(text_color="#000000")
                else:
                    b.configure(text_color="#ffffff")

        def custom_frac_unselect(val):
            orig_frac_unselect(val)
            if val in self.seg_fraction._buttons_dict:
                self.seg_fraction._buttons_dict[val].configure(text_color="#ffffff")

        self.seg_fraction._select_button_by_value = custom_frac_select
        self.seg_fraction._unselect_button_by_value = custom_frac_unselect

        self.seg_fraction.set(t("frac_1_4", self.current_lang))
        self.seg_fraction.pack(side="left", padx=12, pady=6)

        # Sub-frame for Fixed
        self.frame_fixed = ctk.CTkFrame(w_card, fg_color=THEME["sub_box_bg"], corner_radius=6)

        self.lbl_fixed_select = ctk.CTkLabel(self.frame_fixed, text=t("fixed_label", self.current_lang), font=ctk.CTkFont(size=12))
        self.lbl_fixed_select.pack(side="left", padx=12, pady=6)
        
        self.slider_fixed_w = ctk.CTkSlider(
            self.frame_fixed, from_=450, to=1100, number_of_steps=13,
            command=self.on_fixed_slider_changed,
            button_color=THEME["accent_amber"],
            progress_color=THEME["accent_amber"],
            button_hover_color=THEME["accent_gold"]
        )
        self.slider_fixed_w.set(650)
        self.slider_fixed_w.pack(side="left", fill="x", expand=True, padx=12, pady=6)

        self.lbl_fixed_w_val = ctk.CTkLabel(self.frame_fixed, text="650 px", font=ctk.CTkFont(size=12, weight="bold"), width=60)
        self.lbl_fixed_w_val.pack(side="left", padx=(0, 12), pady=6)

        # 2. Font Size & Multipliers Card
        f_card = ctk.CTkFrame(container, corner_radius=8, fg_color=THEME["card_bg"], border_width=1, border_color=THEME["card_border"])
        f_card.pack(fill="x", pady=6, padx=4)

        self.lbl_msg_c2_title = ctk.CTkLabel(f_card, text=t("msg_card2_title", self.current_lang), font=ctk.CTkFont(size=14, weight="bold"), text_color=THEME["accent_gold"])
        self.lbl_msg_c2_title.pack(anchor="w", padx=15, pady=(10, 2))

        # Message and radio communication font size (dlg)
        size_box = ctk.CTkFrame(f_card, fg_color="transparent")
        size_box.pack(fill="x", padx=15, pady=(4, 12))
        self.lbl_msg_fontsize = ctk.CTkLabel(size_box, text=t("msg_font_size_label", self.current_lang), font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"])
        self.lbl_msg_fontsize.pack(anchor="w")

        slider_box2 = ctk.CTkFrame(size_box, fg_color="transparent")
        slider_box2.pack(fill="x", pady=2)
        self.slider_font_size = ctk.CTkSlider(
            slider_box2, from_=10, to=22, number_of_steps=12, command=self.on_font_size_changed,
            button_color=THEME["accent_amber"], progress_color=THEME["accent_amber"], button_hover_color=THEME["accent_gold"]
        )
        self.slider_font_size.set(13)
        self.slider_font_size.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.lbl_font_size_val = ctk.CTkLabel(slider_box2, text="13 pt", font=ctk.CTkFont(size=12, weight="bold"), width=60, text_color=THEME["accent_gold"])
        self.lbl_font_size_val.pack(side="left")

    def on_width_mode_changed(self):
        mode = self.var_width_mode.get()
        self.working_state["msg_width_mode"] = mode
        if mode == "fraction":
            self.frame_fixed.pack_forget()
            self.frame_fraction.pack(fill="x", padx=15, pady=(0, 10))
        else:
            self.frame_fraction.pack_forget()
            self.frame_fixed.pack(fill="x", padx=15, pady=(0, 10))
        self.update_presets_tab_display()

    def on_fraction_segment_changed(self, value):
        if "1/2" in value:
            self.working_state["msg_width_fraction"] = "1/2"
        elif "1/3" in value:
            self.working_state["msg_width_fraction"] = "1/3"
        elif "1/4" in value:
            self.working_state["msg_width_fraction"] = "1/4"
        elif "1/5" in value:
            self.working_state["msg_width_fraction"] = "1/5"
        self.update_presets_tab_display()

    def on_fixed_slider_changed(self, val):
        v = int(round(val / 25.0) * 25)
        self.lbl_fixed_w_val.configure(text=f"{v} px")
        self.working_state["msg_width_fixed"] = v
        self.update_presets_tab_display()

    def on_font_size_changed(self, val):
        v = int(round(val))
        self.lbl_font_size_val.configure(text=f"{v} pt")
        self.working_state["msg_hmd_font_size"] = v
        self.update_presets_tab_display()

    # ---------------- TAB 3: RADIO MENU (No Scrollbar) ----------------
    def build_radio_tab(self):
        container = ctk.CTkFrame(self.tab_radio, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=6)

        card = ctk.CTkFrame(container, corner_radius=8, fg_color=THEME["card_bg"], border_width=1, border_color=THEME["card_border"])
        card.pack(fill="x", pady=6, padx=4)

        self.lbl_radio_title = ctk.CTkLabel(card, text=t("radio_card_title", self.current_lang), font=ctk.CTkFont(size=14, weight="bold"), text_color=THEME["accent_gold"])
        self.lbl_radio_title.pack(anchor="w", padx=15, pady=(10, 2))
        
        self.lbl_radio_desc = ctk.CTkLabel(
            card,
            text=t("radio_card_desc", self.current_lang),
            font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"], justify="left"
        )
        self.lbl_radio_desc.pack(anchor="w", padx=15, pady=(0, 10))

        # Scale slider
        s_box = ctk.CTkFrame(card, fg_color="transparent")
        s_box.pack(fill="x", padx=15, pady=4)
        self.lbl_radio_scale = ctk.CTkLabel(s_box, text=t("radio_scale_label", self.current_lang), font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"])
        self.lbl_radio_scale.pack(anchor="w")

        s_sub = ctk.CTkFrame(s_box, fg_color="transparent")
        s_sub.pack(fill="x", pady=2)
        self.slider_radio_scale = ctk.CTkSlider(
            s_sub, from_=0.7, to=2.2, number_of_steps=30, command=self.on_radio_scale_changed,
            button_color=THEME["accent_amber"], progress_color=THEME["accent_amber"], button_hover_color=THEME["accent_gold"]
        )
        self.slider_radio_scale.set(1.1)
        self.slider_radio_scale.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.lbl_radio_scale_val = ctk.CTkLabel(s_sub, text="1.10x", font=ctk.CTkFont(size=12, weight="bold"), width=60, text_color=THEME["accent_gold"])
        self.lbl_radio_scale_val.pack(side="left")

        # Base Width slider
        w_box = ctk.CTkFrame(card, fg_color="transparent")
        w_box.pack(fill="x", padx=15, pady=4)
        self.lbl_radio_width = ctk.CTkLabel(w_box, text=t("radio_width_label", self.current_lang), font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"])
        self.lbl_radio_width.pack(anchor="w")

        w_sub = ctk.CTkFrame(w_box, fg_color="transparent")
        w_sub.pack(fill="x", pady=2)
        self.slider_radio_w = ctk.CTkSlider(
            w_sub, from_=200, to=400, number_of_steps=20, command=self.on_radio_w_changed,
            button_color=THEME["accent_amber"], progress_color=THEME["accent_amber"], button_hover_color=THEME["accent_gold"]
        )
        self.slider_radio_w.set(280)
        self.slider_radio_w.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.lbl_radio_w_val = ctk.CTkLabel(w_sub, text="280", font=ctk.CTkFont(size=12, weight="bold"), width=60, text_color=THEME["accent_gold"])
        self.lbl_radio_w_val.pack(side="left")

        # Base Height slider
        h_box = ctk.CTkFrame(card, fg_color="transparent")
        h_box.pack(fill="x", padx=15, pady=(4, 12))
        self.lbl_radio_height = ctk.CTkLabel(h_box, text=t("radio_height_label", self.current_lang), font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"])
        self.lbl_radio_height.pack(anchor="w")

        h_sub = ctk.CTkFrame(h_box, fg_color="transparent")
        h_sub.pack(fill="x", pady=2)
        self.slider_radio_h = ctk.CTkSlider(
            h_sub, from_=280, to=550, number_of_steps=27, command=self.on_radio_h_changed,
            button_color=THEME["accent_amber"], progress_color=THEME["accent_amber"], button_hover_color=THEME["accent_gold"]
        )
        self.slider_radio_h.set(380)
        self.slider_radio_h.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.lbl_radio_h_val = ctk.CTkLabel(h_sub, text="380", font=ctk.CTkFont(size=12, weight="bold"), width=60, text_color=THEME["accent_gold"])
        self.lbl_radio_h_val.pack(side="left")

    def on_radio_scale_changed(self, val):
        v = round(val, 2)
        self.lbl_radio_scale_val.configure(text=f"{v:.2f}x")
        self.working_state["radio_hmd_scale"] = v
        self.update_presets_tab_display()

    def on_radio_w_changed(self, val):
        v = int(round(val))
        self.lbl_radio_w_val.configure(text=f"{v}")
        self.working_state["radio_width"] = v
        self.update_presets_tab_display()

    def on_radio_h_changed(self, val):
        v = int(round(val))
        self.lbl_radio_h_val.configure(text=f"{v}")
        self.working_state["radio_height"] = v
        self.update_presets_tab_display()

    # ---------------- TAB 4: OPTIONS.LUA (No Scrollbar) ----------------
    def build_options_tab(self):
        container = ctk.CTkFrame(self.tab_options, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=6)

        card = ctk.CTkFrame(container, corner_radius=8, fg_color=THEME["card_bg"], border_width=1, border_color=THEME["card_border"])
        card.pack(fill="x", pady=6, padx=4)

        self.lbl_opt_title = ctk.CTkLabel(card, text=t("opt_card_title", self.current_lang), font=ctk.CTkFont(size=14, weight="bold"), text_color=THEME["accent_gold"])
        self.lbl_opt_title.pack(anchor="w", padx=15, pady=(10, 2))
        
        self.lbl_opt_desc = ctk.CTkLabel(
            card,
            text=t("opt_card_desc", self.current_lang),
            font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"], justify="left"
        )
        self.lbl_opt_desc.pack(anchor="w", padx=15, pady=(0, 10))

        # messagesFontScale
        fs_box = ctk.CTkFrame(card, fg_color="transparent")
        fs_box.pack(fill="x", padx=15, pady=4)
        self.lbl_opt_scale = ctk.CTkLabel(fs_box, text=t("opt_scale_label", self.current_lang), font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"])
        self.lbl_opt_scale.pack(anchor="w")

        fs_sub = ctk.CTkFrame(fs_box, fg_color="transparent")
        fs_sub.pack(fill="x", pady=2)
        self.slider_opt_font_scale = ctk.CTkSlider(
            fs_sub, from_=0.6, to=1.4, number_of_steps=16, command=self.on_opt_font_scale_changed,
            button_color=THEME["accent_amber"], progress_color=THEME["accent_amber"], button_hover_color=THEME["accent_gold"]
        )
        self.slider_opt_font_scale.set(1.0)
        self.slider_opt_font_scale.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.lbl_opt_font_scale_val = ctk.CTkLabel(fs_sub, text="1.00", font=ctk.CTkFont(size=12, weight="bold"), width=60, text_color=THEME["accent_gold"])
        self.lbl_opt_font_scale_val.pack(side="left")

        # custom IPD
        ipd_box = ctk.CTkFrame(card, fg_color="transparent")
        ipd_box.pack(fill="x", padx=15, pady=4)
        self.lbl_opt_ipd = ctk.CTkLabel(ipd_box, text=t("opt_ipd_label", self.current_lang), font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"])
        self.lbl_opt_ipd.pack(anchor="w")

        ipd_sub = ctk.CTkFrame(ipd_box, fg_color="transparent")
        ipd_sub.pack(fill="x", pady=2)
        self.slider_ipd = ctk.CTkSlider(
            ipd_sub, from_=55, to=75, number_of_steps=20, command=self.on_ipd_changed,
            button_color=THEME["accent_amber"], progress_color=THEME["accent_amber"], button_hover_color=THEME["accent_gold"]
        )
        self.slider_ipd.set(63)
        self.slider_ipd.pack(side="left", fill="x", expand=True, padx=(0, 12))
        self.lbl_ipd_val = ctk.CTkLabel(ipd_sub, text="63 мм", font=ctk.CTkFont(size=12, weight="bold"), width=60, text_color=THEME["accent_gold"])
        self.lbl_ipd_val.pack(side="left")

        # Box mouse cursor checkbox
        self.var_box_cursor = tk.BooleanVar(value=True)
        self.cb_cursor = ctk.CTkCheckBox(
            card, text=t("opt_box_cursor", self.current_lang),
            variable=self.var_box_cursor, command=self.on_box_cursor_changed,
            fg_color=THEME["accent_amber"], hover_color=THEME["accent_amber_hover"]
        )
        self.cb_cursor.pack(anchor="w", padx=15, pady=(6, 12))

    def on_opt_font_scale_changed(self, val):
        v = round(val, 2)
        self.lbl_opt_font_scale_val.configure(text=f"{v:.2f}")
        self.working_state["options_messages_font_scale"] = v
        self.update_presets_tab_display()

    def on_ipd_changed(self, val):
        v = int(round(val))
        unit = " мм" if self.current_lang == "ru" else " mm"
        self.lbl_ipd_val.configure(text=f"{v}{unit}")
        self.working_state["options_custom_ipd"] = v
        self.update_presets_tab_display()

    def on_box_cursor_changed(self):
        self.working_state["options_box_mouse_cursor"] = self.var_box_cursor.get()
        self.update_presets_tab_display()

    # ---------------- TAB 5: OPTIMIZATION & TWEAKS ----------------
    def build_tweaks_tab(self):
        container = ctk.CTkScrollableFrame(
            self.tab_tweaks,
            fg_color="transparent",
            scrollbar_fg_color=THEME["header_bg"],
            scrollbar_button_color=THEME["accent_amber"],
            scrollbar_button_hover_color=THEME["accent_gold"]
        )
        container._scrollbar.configure(width=20, corner_radius=10)
        container.pack(fill="both", expand=True, padx=10, pady=6)

        # 1. VR Background Scene Card (SceneVR.lua)
        scene_card = ctk.CTkFrame(container, corner_radius=8, fg_color=THEME["card_bg"], border_width=1, border_color=THEME["card_border"])
        scene_card.pack(fill="x", pady=6, padx=4)

        header_frame = ctk.CTkFrame(scene_card, fg_color="transparent")
        header_frame.pack(fill="x", padx=15, pady=(10, 2))

        self.lbl_scene_title = ctk.CTkLabel(
            header_frame, text=t("scene_card_title", self.current_lang),
            font=ctk.CTkFont(size=14, weight="bold"), text_color=THEME["accent_gold"],
            justify="left"
        )
        self.lbl_scene_title.pack(side="left")

        shield_path = Path(__file__).resolve().parent / "shield.png"
        if shield_path.exists():
            shield_image = Image.open(shield_path).convert("RGBA")
            self.scene_shield_image = ctk.CTkImage(
                light_image=shield_image,
                dark_image=shield_image,
                size=(20, 20)
            )
            shield_label = ctk.CTkLabel(
                header_frame,
                text="",
                image=self.scene_shield_image,
                cursor="hand2"
            )
            shield_label.pack(side="left", padx=(7, 0))
            HoverTooltip(
                shield_label,
                lambda: t("scene_integrity_tooltip", self.current_lang)
            )

        self.lbl_scene_badge = ctk.CTkLabel(
            header_frame, text="",
            font=ctk.CTkFont(size=12, weight="bold"), text_color="#38bdf8"
        )
        self.lbl_scene_badge.pack(side="right")

        self.lbl_scene_desc = ctk.CTkLabel(
            scene_card, text=t("scene_card_desc", self.current_lang),
            font=ctk.CTkFont(size=13), text_color=THEME["text_secondary"], justify="left",
            wraplength=690
        )
        self.lbl_scene_desc.pack(anchor="w", padx=15, pady=(0, 10))

        opts_box = ctk.CTkFrame(scene_card, fg_color=THEME["sub_box_bg"], corner_radius=6, border_width=1, border_color="#363a45")
        opts_box.pack(fill="x", padx=15, pady=(0, 14))

        from scene_vr_manager import detect_scene_vr_mode, MODE_SKY, MODE_ORIGINAL, MODE_BLACK
        current_mode = detect_scene_vr_mode(self.target_files)
        self.var_scene_mode = tk.StringVar(value=current_mode)

        def make_scene_radio_row(parent, value, title_key, sub_key):
            row_frame = ctk.CTkFrame(parent, fg_color="transparent")
            row_frame.pack(fill="x", padx=12, pady=6)

            rb = PremiumRadioButton(
                row_frame,
                text=t(title_key, self.current_lang),
                variable=self.var_scene_mode,
                value=value,
                command=self.on_scene_mode_changed,
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color=THEME["accent_amber"],
                hover_color=THEME["accent_amber_hover"],
                border_color="#6b7280"
            )
            rb.pack(anchor="w")

            sub_lbl = ctk.CTkLabel(
                row_frame,
                text=t(sub_key, self.current_lang),
                font=ctk.CTkFont(size=13),
                text_color=THEME["text_secondary"],
                justify="left",
                wraplength=650
            )
            sub_lbl.pack(anchor="w", padx=(28, 0), pady=(1, 0))
            return rb, sub_lbl

        self.rb_scene_sky, self.lbl_scene_sky_sub = make_scene_radio_row(
            opts_box, MODE_SKY, "scene_opt_sky", "scene_opt_sky_sub"
        )
        self.rb_scene_black, self.lbl_scene_black_sub = make_scene_radio_row(
            opts_box, MODE_BLACK, "scene_opt_black", "scene_opt_black_sub"
        )
        self.rb_scene_orig, self.lbl_scene_orig_sub = make_scene_radio_row(
            opts_box, MODE_ORIGINAL, "scene_opt_original", "scene_opt_original_sub"
        )
        self.lbl_scene_original_warning = ctk.CTkLabel(
            opts_box,
            text="",
            font=ctk.CTkFont(size=11),
            text_color=THEME["status_amber_text"],
            justify="left",
            wraplength=700
        )
        self.refresh_scene_original_control()

        def resize_scene_text(event):
            wraplength = max(160, event.width - 40)
            self.lbl_scene_desc.configure(wraplength=wraplength)
            self.lbl_scene_sky_sub.configure(wraplength=wraplength - 28)
            self.lbl_scene_black_sub.configure(wraplength=wraplength - 28)
            self.lbl_scene_orig_sub.configure(wraplength=wraplength - 28)
            self.lbl_scene_original_warning.configure(wraplength=wraplength - 64)

        scene_card.bind("<Configure>", resize_scene_text, add="+")
        self.update_scene_vr_badge()

        # 2. Default first waypoint altitude and type (RouteTool.lua)
        route_card = ctk.CTkFrame(container, corner_radius=8, fg_color=THEME["card_bg"], border_width=1, border_color=THEME["card_border"])
        route_card.pack(fill="x", pady=6, padx=4)

        route_header = ctk.CTkFrame(route_card, fg_color="transparent")
        route_header.pack(fill="x", padx=15, pady=(10, 2))

        self.lbl_route_tool_title = ctk.CTkLabel(
            route_header,
            text=t("route_tool_card_title", self.current_lang),
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=THEME["accent_gold"],
            justify="left",
            anchor="w"
        )
        self.lbl_route_tool_title.pack(side="left")

        route_shield_path = Path(__file__).resolve().parent / "shield.png"
        if route_shield_path.exists():
            route_shield_raw = Image.open(route_shield_path).convert("RGBA")
            self.route_tool_shield_image = ctk.CTkImage(
                light_image=route_shield_raw,
                dark_image=route_shield_raw,
                size=(20, 20)
            )
            self.route_tool_shield_label = ctk.CTkLabel(
                route_header,
                text="",
                image=self.route_tool_shield_image,
                cursor="hand2"
            )
            self.route_tool_shield_label.pack(side="left", padx=(7, 0))
            HoverTooltip(
                self.route_tool_shield_label,
                lambda: t("route_tool_integrity_tooltip", self.current_lang)
            )

        self.lbl_route_tool_desc = ctk.CTkLabel(
            route_card,
            text=t("route_tool_card_desc", self.current_lang),
            font=ctk.CTkFont(size=13),
            text_color=THEME["text_secondary"],
            justify="left",
            anchor="w"
        )
        self.lbl_route_tool_desc.pack(fill="x", padx=15, pady=(0, 10))

        def resize_route_tool_description(event):
            wraplength = max(160, event.width - 40)
            self.lbl_route_tool_title.configure(wraplength=max(160, wraplength - 60))
            self.lbl_route_tool_desc.configure(wraplength=wraplength)
            self.lbl_route_tool_error.configure(wraplength=wraplength - 24)

        route_controls = ctk.CTkFrame(
            route_card,
            fg_color=THEME["sub_box_bg"],
            corner_radius=6,
            border_width=1,
            border_color="#363a45"
        )
        route_controls.pack(fill="x", padx=15, pady=(0, 14))
        self.var_route_tool_enabled = tk.BooleanVar(value=False)
        self.switch_route_tool = ctk.CTkSwitch(
            route_controls,
            text=t("route_tool_switch", self.current_lang),
            variable=self.var_route_tool_enabled,
            command=self.on_route_tool_toggled,
            font=ctk.CTkFont(size=13, weight="bold"),
            progress_color=THEME["accent_amber"],
            button_color=THEME["text_primary"],
            button_hover_color=THEME["text_primary"],
            text_color=THEME["text_primary"],
            onvalue=True,
            offvalue=False
        )
        self.switch_route_tool.pack(anchor="w", padx=12, pady=(12, 6))
        self.lbl_route_tool_error = ctk.CTkLabel(
            route_controls,
            text="",
            font=ctk.CTkFont(size=12),
            text_color=THEME["status_amber_text"],
            justify="left",
            wraplength=420
        )
        self.lbl_route_tool_error.pack(anchor="w", padx=(12, 12), pady=(0, 10))
        route_card.bind("<Configure>", resize_route_tool_description, add="+")
        self.refresh_route_tool_control()

        # 3. Engine & Graphics Tweaks (autoexec.cfg)
        cfg_card = ctk.CTkFrame(container, corner_radius=8, fg_color=THEME["card_bg"], border_width=1, border_color=THEME["card_border"])
        cfg_card.pack(fill="x", pady=6, padx=4)

        cfg_header = ctk.CTkFrame(cfg_card, fg_color="transparent")
        cfg_header.pack(fill="x", padx=15, pady=(10, 2))

        self.lbl_cfg_title = ctk.CTkLabel(
            cfg_header, text=t("cfg_card_title", self.current_lang),
            font=ctk.CTkFont(size=14, weight="bold"), text_color=THEME["accent_gold"]
        )
        self.lbl_cfg_title.pack(side="left")

        self.lbl_cfg_badge = ctk.CTkLabel(
            cfg_header, text="",
            font=ctk.CTkFont(size=11, weight="bold"), text_color=THEME["text_secondary"],
            fg_color="transparent", corner_radius=6, padx=8, pady=2
        )
        self.lbl_cfg_badge.pack(side="right")

        self.lbl_cfg_desc = ctk.CTkLabel(
            cfg_card, text=t("cfg_card_desc", self.current_lang),
            font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"], justify="left"
        )
        self.lbl_cfg_desc.pack(anchor="w", padx=15, pady=(0, 8))

        cfg_preview_box = ctk.CTkFrame(cfg_card, fg_color=THEME["sub_box_bg"], corner_radius=6, border_width=1, border_color="#363a45")
        cfg_preview_box.pack(fill="x", padx=15, pady=(0, 14))

        self.autoexec_widget_rows = {}
        self.autoexec_errors = {}
        self.autoexec_global_error = None
        tweak_option_columns = (
            (
                ("DLSS_Preset", "cfg_dlss_name", "cfg_dlss_desc"),
                ("HUD_MFD_after_DLSS", "cfg_hud_name", "cfg_hud_desc"),
                ("disable_write_track", "cfg_track_name", "cfg_track_desc"),
                ("no_device_hotplug", "cfg_hotplug_name", "cfg_hotplug_desc"),
            ),
            (
                ("options.graphics.stereo_mode_use_shared_parser", "cfg_shared_parser_name", "cfg_shared_parser_desc"),
            ),
        )
        for column_options in tweak_option_columns:
            column = ctk.CTkFrame(cfg_preview_box, fg_color="transparent")
            column.pack(side="left", anchor="nw", padx=4, pady=4)
            for key, name_key, description_key in column_options:
                row = ctk.CTkFrame(column, fg_color="transparent")
                row.pack(fill="x", padx=4, pady=2, anchor="w")

                variable = tk.BooleanVar(value=False)
                checkbox = ctk.CTkCheckBox(
                    row,
                    text="",
                    variable=variable,
                    command=lambda setting=key: self.on_autoexec_boolean_changed(setting),
                    width=14,
                    height=14,
                    checkbox_width=14,
                    checkbox_height=14,
                    corner_radius=3,
                    border_width=1,
                    fg_color=THEME["accent_amber"],
                    hover_color=THEME["accent_amber_hover"],
                    border_color="#656873",
                    checkmark_color=THEME["accent_dark_text"]
                )
                checkbox.pack(side="left", padx=(4, 3))

                name_label = ctk.CTkLabel(
                    row,
                    text=t(name_key, self.current_lang),
                    font=ctk.CTkFont(size=13, weight="bold"),
                    text_color=THEME["text_primary"]
                )
                name_label.pack(side="left")

                option_widgets = {
                    "variable": variable,
                    "checkbox": checkbox,
                    "name": name_label,
                }
                if key == "DLSS_Preset":
                    self.cb_dlss_preset = DLSSPresetPicker(
                        row,
                        command=self.on_dlss_preset_selected
                    )
                    self.cb_dlss_preset.set("K")
                    self.cb_dlss_preset.pack(side="left", padx=(4, 0))
                    option_widgets["combo"] = self.cb_dlss_preset

                info_label = ctk.CTkLabel(
                    row, text="ⓘ", font=ctk.CTkFont(size=13, weight="bold"),
                    text_color=THEME["text_muted"], cursor="question_arrow"
                )
                info_label.pack(side="left", padx=(6, 0))
                HoverTooltip(info_label, lambda desc=description_key: t(desc, self.current_lang))
                option_widgets["info"] = info_label

                warning_label = ctk.CTkLabel(
                    row, text="", font=ctk.CTkFont(size=13, weight="bold"),
                    text_color=THEME["status_amber_text"], cursor="question_arrow"
                )
                warning_label.pack(side="left", padx=(6, 0))
                HoverTooltip(warning_label, lambda setting=key: self._autoexec_error_tooltip(setting))
                option_widgets["warning"] = warning_label
                self.autoexec_widget_rows[key] = option_widgets

        self.refresh_autoexec_controls()

    def update_scene_vr_badge(self):
        if not hasattr(self, "lbl_scene_badge"):
            return
        from scene_vr_manager import detect_scene_vr_mode, MODE_SKY, MODE_ORIGINAL, MODE_BLACK
        mode = detect_scene_vr_mode(self.target_files)
        lang = self.current_lang
        label_prefix = t("scene_status_label", lang)
        if mode == MODE_SKY:
            txt = f"{label_prefix} {t('scene_status_sky', lang)}"
            color = THEME["status_green_text"]
        elif mode == MODE_ORIGINAL:
            txt = f"{label_prefix} {t('scene_status_original', lang)}"
            color = "#a1a1aa"
        elif mode == MODE_BLACK:
            txt = f"{label_prefix} {t('scene_status_black', lang)}"
            color = THEME["status_green_text"]
        else:
            txt = f"{label_prefix} {t('scene_status_unknown', lang)}"
            color = THEME["accent_amber"]

        self.lbl_scene_badge.configure(text=txt, text_color=color)

    def _autoexec_error_tooltip(self, key):
        if self.autoexec_global_error:
            return self.autoexec_global_error
        error = self.autoexec_errors.get(key)
        if error == "duplicate":
            return t("cfg_error_duplicate", self.current_lang)
        if error == "invalid":
            return t("cfg_error_invalid", self.current_lang)
        return ""

    def refresh_autoexec_controls(self):
        from autoexec_manager import ENABLED_TWEAK_VALUES, read_autoexec_settings

        path = self.target_files.get("autoexec_cfg")
        if path is None:
            self.autoexec_errors = {}
            self.autoexec_global_error = t("cfg_path_unavailable", self.current_lang)
            self.lbl_cfg_badge.configure(
                text=t("cfg_badge_error", self.current_lang),
                text_color=THEME["status_red_text"]
            )
            if hasattr(self, "status_label"):
                self.update_status_display(t("cfg_path_unavailable", self.current_lang))
            for widgets in self.autoexec_widget_rows.values():
                widgets["checkbox"].configure(state="disabled")
                widgets["variable"].set(False)
                widgets["name"].configure(text_color=THEME["text_primary"])
                widgets["warning"].configure(text="⚠")
                if "combo" in widgets:
                    widgets["combo"].configure(state="disabled")
                    widgets["combo"].set("K")
            return

        try:
            values, errors = read_autoexec_settings(path)
        except (OSError, UnicodeError) as error:
            self.autoexec_errors = {}
            self.autoexec_global_error = t("cfg_read_error", self.current_lang, error=str(error))
            self.lbl_cfg_badge.configure(
                text=t("cfg_badge_error", self.current_lang),
                text_color=THEME["status_red_text"]
            )
            if hasattr(self, "status_label"):
                self.update_status_display(self.autoexec_global_error)
            for widgets in self.autoexec_widget_rows.values():
                widgets["checkbox"].configure(state="disabled")
                widgets["variable"].set(False)
                widgets["name"].configure(text_color=THEME["text_primary"])
                widgets["warning"].configure(text="⚠")
                if "combo" in widgets:
                    widgets["combo"].configure(state="disabled")
                    widgets["combo"].set("K")
            return

        self.autoexec_global_error = None
        self.autoexec_errors = errors
        if path.exists():
            self.lbl_cfg_badge.configure(
                text=t("cfg_badge_found", self.current_lang),
                text_color=THEME["status_green_text"]
            )
        else:
            self.lbl_cfg_badge.configure(
                text=t("cfg_badge_missing", self.current_lang),
                text_color=THEME["text_secondary"]
            )

        for key, widgets in self.autoexec_widget_rows.items():
            value = values[key]
            invalid = key in errors
            widgets["warning"].configure(text="⚠" if invalid else "")
            widgets["checkbox"].configure(state="disabled" if invalid else "normal")
            enabled = (
                isinstance(value, bool) and value is ENABLED_TWEAK_VALUES[key]
            ) or (key == "DLSS_Preset" and isinstance(value, str))
            widgets["variable"].set(enabled)
            widgets["name"].configure(
                text_color=THEME["accent_amber"] if widgets["variable"].get() else THEME["text_primary"]
            )
            if "combo" in widgets:
                widgets["combo"].configure(state="normal" if not invalid else "disabled")
                widgets["combo"].set(value if isinstance(value, str) else "K")

    def on_autoexec_boolean_changed(self, key):
        from autoexec_manager import ENABLED_TWEAK_VALUES

        value = bool(self.autoexec_widget_rows[key]["variable"].get())
        if key == "DLSS_Preset":
            if value:
                self._apply_dlss_preset(self.cb_dlss_preset.get())
            else:
                self._write_autoexec_setting(key, False)
            return
        target_value = ENABLED_TWEAK_VALUES[key]
        self._write_autoexec_setting(key, target_value if value else not target_value)

    def on_dlss_preset_selected(self, value):
        if self.autoexec_widget_rows["DLSS_Preset"]["variable"].get():
            self._apply_dlss_preset(value)

    def on_dlss_preset_edited(self, event=None):
        if self.autoexec_widget_rows["DLSS_Preset"]["variable"].get():
            self._apply_dlss_preset(self.cb_dlss_preset.get())

    def _apply_dlss_preset(self, value):
        preset = value.strip()
        if len(preset) != 1 or not preset.isascii() or not preset.isalpha():
            self.refresh_autoexec_controls()
            self.show_dark_error(
                t("dialog_error_title", self.current_lang),
                t("cfg_invalid_preset_input", self.current_lang)
            )
            return
        self._write_autoexec_setting("DLSS_Preset", preset.upper())

    def _write_autoexec_setting(self, key, value):
        from autoexec_manager import write_autoexec_setting

        option_name_key = {
            "DLSS_Preset": "cfg_dlss_name",
            "HUD_MFD_after_DLSS": "cfg_hud_name",
            "disable_write_track": "cfg_track_name",
            "no_device_hotplug": "cfg_hotplug_name",
            "options.graphics.stereo_mode_use_shared_parser": "cfg_shared_parser_name",
        }[key]
        option_name = t(option_name_key, self.current_lang)
        try:
            changed = write_autoexec_setting(self.target_files["autoexec_cfg"], key, value)
            self.refresh_autoexec_controls()
            status_key = "cfg_option_applied" if changed else "cfg_option_unchanged"
            self.update_status_by_key(status_key, option=option_name)
        except (OSError, UnicodeError, ValueError) as error:
            self.refresh_autoexec_controls()
            self.show_dark_error(
                t("dialog_error_title", self.current_lang),
                t("cfg_apply_error", self.current_lang, option=option_name, error=str(error))
            )

    def on_scene_mode_changed(self):
        from scene_vr_manager import apply_scene_vr_mode, detect_scene_vr_mode
        mode = self.var_scene_mode.get()
        success, err = apply_scene_vr_mode(self.target_files, mode)
        if success:
            self.refresh_scene_original_control()
            self.update_scene_vr_badge()
            self.update_presets_tab_display()
            mode_name = t(f"scene_status_{mode}", self.current_lang)
            self.update_status_by_key("scene_applied_status", mode=mode_name)
        else:
            self.var_scene_mode.set(detect_scene_vr_mode(self.target_files))
            self.refresh_scene_original_control()
            self.update_scene_vr_badge()
            self.update_presets_tab_display()
            err_msg = f"Не удалось изменить SceneVR.lua:\n{err}" if self.current_lang == "ru" else f"Failed to update SceneVR.lua:\n{err}"
            self.show_dark_error(t("dialog_error_title", self.current_lang), err_msg)

    def refresh_route_tool_control(self):
        from route_tool_manager import (
            RouteToolError,
            ensure_route_tool_baseline,
            is_route_tool_enabled,
            read_route_tool_defaults,
        )

        if not hasattr(self, "switch_route_tool"):
            return

        if not self.route_tool_path.is_file():
            self.var_route_tool_enabled.set(False)
            self.switch_route_tool.configure(state="disabled")
            self.lbl_route_tool_error.configure(text=t("route_tool_file_missing", self.current_lang))
            return

        try:
            defaults = read_route_tool_defaults(self.route_tool_path)
            is_enabled = is_route_tool_enabled(defaults)
            baseline_available = ensure_route_tool_baseline(self.route_tool_path)
        except (OSError, RouteToolError) as error:
            self.var_route_tool_enabled.set(False)
            self.switch_route_tool.configure(state="disabled")
            self.lbl_route_tool_error.configure(
                text=t("route_tool_read_error", self.current_lang, error=str(error))
            )
            return

        self.var_route_tool_enabled.set(is_enabled)
        self.switch_route_tool.configure(state="normal" if (not is_enabled or baseline_available) else "disabled")
        if is_enabled and not baseline_available:
            self.lbl_route_tool_error.configure(text=t("route_tool_baseline_missing", self.current_lang))
        else:
            self.lbl_route_tool_error.configure(text="")

    def on_route_tool_toggled(self):
        from route_tool_manager import RouteToolError, set_route_tool_enabled

        try:
            changed = set_route_tool_enabled(
                self.route_tool_path,
                bool(self.var_route_tool_enabled.get())
            )
            self.refresh_route_tool_control()
            self.update_presets_tab_display()
            self.update_status_by_key(
                "route_tool_applied" if changed else "route_tool_unchanged"
            )
        except (OSError, RouteToolError) as error:
            self.refresh_route_tool_control()
            self.show_dark_error(
                t("dialog_error_title", self.current_lang),
                t("route_tool_apply_error", self.current_lang, error=str(error))
            )

    # ---------------- TAB 6: PATHS & BACKUPS (No Scrollbar) ----------------
    def build_backups_tab(self):
        container = ctk.CTkFrame(self.tab_backups, fg_color="transparent")
        container.pack(fill="both", expand=True, padx=10, pady=6)

        # Paths Card
        paths_card = ctk.CTkFrame(container, corner_radius=8, fg_color=THEME["card_bg"], border_width=1, border_color=THEME["card_border"])
        paths_card.pack(fill="x", pady=4, padx=4)

        paths_header = ctk.CTkFrame(paths_card, fg_color="transparent")
        paths_header.pack(fill="x", padx=15, pady=(8, 2))

        self.lbl_paths_title = ctk.CTkLabel(paths_header, text=t("paths_title", self.current_lang), font=ctk.CTkFont(size=14, weight="bold"), text_color=THEME["accent_gold"])
        self.lbl_paths_title.pack(side="left")

        self.btn_autodetect = PillButton(
            paths_header,
            text=t("btn_autodetect", self.current_lang),
            width=130,
            height=26,
            corner_radius=13,
            fg_color=THEME["btn_gray"],
            hover_color=THEME["btn_gray_hover"],
            text_color=THEME["accent_amber"],
            font=ctk.CTkFont(size=11, weight="bold"),
            command=self.action_autodetect_paths
        )
        self.btn_autodetect.pack(side="right")

        # DCS Path
        self.lbl_dcs_path = ctk.CTkLabel(paths_card, text=t("dcs_path_label", self.current_lang), font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"])
        self.lbl_dcs_path.pack(anchor="w", padx=15, pady=(4, 0))
        p_row1 = ctk.CTkFrame(paths_card, fg_color="transparent")
        p_row1.pack(fill="x", padx=15, pady=(2, 2))
        self.entry_dcs_path = ctk.CTkEntry(p_row1)
        self.entry_dcs_path.insert(0, self.dcs_path)
        self.entry_dcs_path.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_dcs_path.bind("<FocusOut>", lambda e: self.on_dcs_path_entry_changed())
        self.entry_dcs_path.bind("<Return>", lambda e: self.on_dcs_path_entry_changed())
        self.btn_browse_dcs = PillButton(
            p_row1, text=t("btn_browse", self.current_lang), width=90, height=28,
            fg_color=THEME["btn_gray"],
            hover_color=THEME["btn_gray_hover"], text_color=THEME["text_primary"], font=ctk.CTkFont(size=12),
            command=self.browse_dcs_path
        )
        self.btn_browse_dcs.pack(side="left")

        self.lbl_dcs_status = ctk.CTkLabel(paths_card, text="", font=ctk.CTkFont(size=11, weight="bold"))
        self.lbl_dcs_status.pack(anchor="w", padx=15, pady=(0, 0))
        self.lbl_dcs_hint = ctk.CTkLabel(paths_card, text=t("dcs_path_hint", self.current_lang), font=ctk.CTkFont(size=11), text_color=THEME["text_muted"])
        self.lbl_dcs_hint.pack(anchor="w", padx=15, pady=(0, 6))

        # Saved Games Path
        self.lbl_sg_path = ctk.CTkLabel(paths_card, text=t("sg_path_label", self.current_lang), font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"])
        self.lbl_sg_path.pack(anchor="w", padx=15, pady=(2, 0))
        p_row2 = ctk.CTkFrame(paths_card, fg_color="transparent")
        p_row2.pack(fill="x", padx=15, pady=(2, 2))
        self.entry_sg_path = ctk.CTkEntry(p_row2)
        self.entry_sg_path.insert(0, self.saved_games_path)
        self.entry_sg_path.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.entry_sg_path.bind("<FocusOut>", lambda e: self.on_sg_path_entry_changed())
        self.entry_sg_path.bind("<Return>", lambda e: self.on_sg_path_entry_changed())
        self.btn_browse_sg = PillButton(
            p_row2, text=t("btn_browse", self.current_lang), width=90, height=28,
            fg_color=THEME["btn_gray"],
            hover_color=THEME["btn_gray_hover"], text_color=THEME["text_primary"], font=ctk.CTkFont(size=12),
            command=self.browse_sg_path
        )
        self.btn_browse_sg.pack(side="left")

        self.lbl_sg_status = ctk.CTkLabel(paths_card, text="", font=ctk.CTkFont(size=11, weight="bold"))
        self.lbl_sg_status.pack(anchor="w", padx=15, pady=(0, 0))
        self.lbl_sg_hint = ctk.CTkLabel(paths_card, text=t("sg_path_hint", self.current_lang), font=ctk.CTkFont(size=11), text_color=THEME["text_muted"])
        self.lbl_sg_hint.pack(anchor="w", padx=15, pady=(0, 8))

        # Clean Factory Backup Card
        b_card = ctk.CTkFrame(container, corner_radius=8, fg_color=THEME["card_bg"], border_width=1, border_color=THEME["card_border"])
        b_card.pack(fill="x", pady=6, padx=4)

        self.lbl_clean_title = ctk.CTkLabel(b_card, text=t("clean_backup_title", self.current_lang), font=ctk.CTkFont(size=14, weight="bold"), text_color=THEME["accent_gold"])
        self.lbl_clean_title.pack(anchor="w", padx=15, pady=(12, 4))

        self.lbl_clean_desc = ctk.CTkLabel(
            b_card,
            text=t("clean_backup_desc", self.current_lang),
            font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"], justify="left"
        )
        self.lbl_clean_desc.pack(anchor="w", padx=15, pady=(0, 12))

        # Status & Action box
        action_box = ctk.CTkFrame(b_card, fg_color=THEME["sub_box_bg"], corner_radius=6)
        action_box.pack(fill="x", padx=15, pady=(0, 14))

        self.lbl_clean_status = ctk.CTkLabel(
            action_box,
            text=t("clean_backup_status", self.current_lang),
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color="#4ade80"
        )
        self.lbl_clean_status.pack(side="left", padx=15, pady=10)

        self.btn_restore = PillButton(
            action_box,
            text=t("btn_restore_clean", self.current_lang),
            height=30,
            corner_radius=15,
            fg_color=THEME["btn_gray"],
            hover_color=THEME["btn_gray_hover"],
            text_color=THEME["text_primary"],
            font=ctk.CTkFont(size=12),
            command=self.action_restore_clean
        )
        self.btn_restore.pack(side="right", padx=15, pady=8)

    def browse_dcs_path(self):
        title = "Выберите папку установки DCS World или файл DCS.exe" if self.current_lang == "ru" else "Select DCS World Installation Folder or DCS.exe"
        d = filedialog.askdirectory(initialdir=self.dcs_path, title=title)
        if d:
            normalized = normalize_dcs_path(d)
            self.dcs_path = normalized
            self.entry_dcs_path.delete(0, "end")
            self.entry_dcs_path.insert(0, self.dcs_path)
            self.app_settings["dcs_path"] = self.dcs_path
            save_settings(self.app_settings)
            self.target_files = get_target_files(self.dcs_path, self.saved_games_path)
            ensure_clean_backup(self.target_files)
            self.action_refresh_live_state()

    def browse_sg_path(self):
        title = "Выберите папку Saved Games DCS" if self.current_lang == "ru" else "Select DCS Saved Games Folder"
        d = filedialog.askdirectory(initialdir=self.saved_games_path, title=title)
        if d:
            self.saved_games_path = str(Path(d))
            self.entry_sg_path.delete(0, "end")
            self.entry_sg_path.insert(0, self.saved_games_path)
            self.app_settings["saved_games_path"] = self.saved_games_path
            save_settings(self.app_settings)
            self.target_files = get_target_files(self.dcs_path, self.saved_games_path)
            ensure_clean_backup(self.target_files)
            self.action_refresh_live_state()

    def on_dcs_path_entry_changed(self):
        new_path = normalize_dcs_path(self.entry_dcs_path.get().strip())
        if new_path and new_path != self.dcs_path:
            self.dcs_path = new_path
            self.entry_dcs_path.delete(0, "end")
            self.entry_dcs_path.insert(0, self.dcs_path)
            self.app_settings["dcs_path"] = self.dcs_path
            save_settings(self.app_settings)
            self.target_files = get_target_files(self.dcs_path, self.saved_games_path)
            ensure_clean_backup(self.target_files)
            self.action_refresh_live_state()

    def on_sg_path_entry_changed(self):
        new_path = self.entry_sg_path.get().strip()
        if new_path and new_path != self.saved_games_path:
            self.saved_games_path = new_path
            self.app_settings["saved_games_path"] = self.saved_games_path
            save_settings(self.app_settings)
            self.target_files = get_target_files(self.dcs_path, self.saved_games_path)
            ensure_clean_backup(self.target_files)
            self.action_refresh_live_state()

    def action_autodetect_paths(self):
        """Automatically scans registry and drives to detect DCS World and Saved Games folders."""
        detected_dcs = detect_dcs_install_path()
        detected_sg = detect_saved_games_path()
        updated = False

        if detected_dcs and detected_dcs != self.dcs_path:
            self.dcs_path = detected_dcs
            self.entry_dcs_path.delete(0, "end")
            self.entry_dcs_path.insert(0, self.dcs_path)
            self.app_settings["dcs_path"] = self.dcs_path
            updated = True

        if detected_sg and detected_sg != self.saved_games_path:
            self.saved_games_path = detected_sg
            self.entry_sg_path.delete(0, "end")
            self.entry_sg_path.insert(0, self.saved_games_path)
            self.app_settings["saved_games_path"] = self.saved_games_path
            updated = True

        if updated or (detected_dcs and detected_sg):
            save_settings(self.app_settings)
            self.target_files = get_target_files(self.dcs_path, self.saved_games_path)
            ensure_clean_backup(self.target_files)
            self.action_refresh_live_state()
            self.show_dark_info(t("dialog_success_title", self.current_lang), t("autodetect_found_msg", self.current_lang))
        else:
            self.show_dark_error(t("dialog_error_title", self.current_lang), t("autodetect_not_found_msg", self.current_lang))

    def update_status_by_key(self, key: str, **kwargs):
        self.current_status_key = key
        self.current_status_kwargs = kwargs
        msg = t(key, self.current_lang, **kwargs)
        self.status_label.configure(text=f"ℹ️ {msg}")

    def update_status_display(self, text: str):
        self.current_status_key = None
        self.status_label.configure(text=f"ℹ️ {text}")

    # ---------------- FOOTER & ACTIONS ----------------
    def create_footer(self):
        footer_frame = ctk.CTkFrame(
            self,
            height=50,
            corner_radius=10,
            fg_color=THEME["header_bg"]
        )
        footer_frame.pack(fill="x", padx=15, pady=(0, 10))
        footer_frame.pack_propagate(False)

        # Status text
        self.status_label = ctk.CTkLabel(
            footer_frame, text="", font=ctk.CTkFont(size=12), text_color=THEME["text_secondary"]
        )
        self.status_label.pack(side="left", padx=15, pady=8)

        # Save Custom Profile button (Pill Shape h=34, r=17, regular font)
        self.btn_apply = PillButton(
            footer_frame,
            text=t("btn_save_custom", self.current_lang),
            width=220,
            height=34,
            corner_radius=17,
            fg_color=THEME["accent_amber"],
            hover_color=THEME["accent_amber_hover"],
            text_color=THEME["accent_dark_text"],
            font=ctk.CTkFont(size=12),
            command=self.action_save_custom_profile
        )
        self.btn_apply.pack(side="right", padx=(6, 15), pady=8)
        HoverTooltip(
            self.btn_apply,
            lambda: t("btn_save_custom_tooltip", self.current_lang)
        )

        # Reload / Refresh files button (Pill shaped, h=34, r=17)
        self.btn_refresh = PillButton(
            footer_frame,
            text=t("btn_reload_files", self.current_lang),
            width=160,
            height=34,
            corner_radius=17,
            fg_color=THEME["btn_gray"],
            hover_color=THEME["btn_gray_hover"],
            text_color=THEME["text_primary"],
            font=ctk.CTkFont(size=12),
            command=self.action_refresh_live_state
        )
        self.btn_refresh.pack(side="right", padx=(0, 6), pady=8)

    def update_all_translations(self):
        """Refreshes all text across the entire interface when language changes."""
        lang = self.current_lang
        
        # Header
        self.lbl_app_title.configure(text=t("app_title", lang))
        self.lbl_app_sub.configure(text=t("app_subtitle", lang))
        
        # Badges
        self.update_status_badges()

        # Tab button titles
        tab_names = {
            "presets": t("tab_presets", lang),
            "messages": t("tab_messages", lang),
            "radio": t("tab_radio", lang),
            "tweaks": t("tab_tweaks", lang),
            "backups": t("tab_backups", lang)
        }
        for tab_id, display_text in tab_names.items():
            self.tabview.set_tab_text(tab_id, display_text)

        # Tab 1: Presets
        self.lbl_presets_info.configure(text=t("presets_info", lang))
        for key, w in self.preset_widgets.items():
            if key == "custom":
                w["title"].configure(text=t("preset_custom_title", lang))
                w["btn"].configure(text=t("btn_load_custom", lang))
            else:
                w["title"].configure(text=get_preset_title(key, lang))
                w["desc"].configure(text=get_preset_desc(key, lang))
                w["btn"].configure(text=t("btn_select_preset", lang))
        self.update_presets_tab_display()

        # Tab 2: Messages
        self.lbl_msg_c1_title.configure(text=t("msg_card1_title", lang))
        self.lbl_msg_c1_desc.configure(text=t("msg_card1_desc", lang))
        self.r_frac.configure(text=t("mode_fraction", lang))
        self.r_fixed.configure(text=t("mode_fixed", lang))
        self.lbl_frac_select.configure(text=t("fraction_label", lang))
        self.lbl_fixed_select.configure(text=t("fixed_label", lang))
        
        # Update fraction segment buttons for new language
        cur_frac = self.working_state.get("msg_width_fraction", "1/4")
        frac_map = {
            "1/2": t("frac_1_2", lang),
            "1/3": t("frac_1_3", lang),
            "1/4": t("frac_1_4", lang),
            "1/5": t("frac_1_5", lang),
        }
        self.seg_fraction.configure(values=list(frac_map.values()))
        self.seg_fraction.set(frac_map.get(cur_frac, frac_map["1/4"]))
        for v, b in self.seg_fraction._buttons_dict.items():
            if v == self.seg_fraction.get():
                b.configure(text_color="#000000")
            else:
                b.configure(text_color="#ffffff")
        self.lbl_msg_c2_title.configure(text=t("msg_card2_title", lang))
        self.lbl_msg_fontsize.configure(text=t("msg_font_size_label", lang))

        # Tab 3: Radio
        self.lbl_radio_title.configure(text=t("radio_card_title", lang))
        self.lbl_radio_desc.configure(text=t("radio_card_desc", lang))
        self.lbl_radio_scale.configure(text=t("radio_scale_label", lang))
        self.lbl_radio_width.configure(text=t("radio_width_label", lang))
        self.lbl_radio_height.configure(text=t("radio_height_label", lang))

        # Tab 4: Options
        self.lbl_opt_title.configure(text=t("opt_card_title", lang))
        self.lbl_opt_desc.configure(text=t("opt_card_desc", lang))
        self.lbl_opt_scale.configure(text=t("opt_scale_label", lang))
        self.lbl_opt_ipd.configure(text=t("opt_ipd_label", lang))
        self.cb_cursor.configure(text=t("opt_box_cursor", lang))
        ipd_unit = " мм" if lang == "ru" else " mm"
        self.lbl_ipd_val.configure(text=f"{int(round(self.slider_ipd.get()))}{ipd_unit}")

        # Tab 5: Optimization & Tweaks
        if hasattr(self, "lbl_scene_title"):
            self.lbl_scene_title.configure(text=t("scene_card_title", lang))
            self.lbl_scene_desc.configure(text=t("scene_card_desc", lang))
            self.lbl_route_tool_title.configure(text=t("route_tool_card_title", lang))
            self.lbl_route_tool_desc.configure(text=t("route_tool_card_desc", lang))
            self.switch_route_tool.configure(text=t("route_tool_switch", lang))
            self.rb_scene_sky.configure(text=t("scene_opt_sky", lang))
            self.lbl_scene_sky_sub.configure(text=t("scene_opt_sky_sub", lang))
            self.rb_scene_orig.configure(text=t("scene_opt_original", lang))
            self.lbl_scene_orig_sub.configure(text=t("scene_opt_original_sub", lang))
            self.rb_scene_black.configure(text=t("scene_opt_black", lang))
            self.lbl_scene_black_sub.configure(text=t("scene_opt_black_sub", lang))
            self.refresh_scene_original_control()
            self.update_scene_vr_badge()

            self.lbl_cfg_title.configure(text=t("cfg_card_title", lang))
            self.lbl_cfg_desc.configure(text=t("cfg_card_desc", lang))
            for key, name_key in (
                ("DLSS_Preset", "cfg_dlss_name"),
                ("HUD_MFD_after_DLSS", "cfg_hud_name"),
                ("disable_write_track", "cfg_track_name"),
                ("no_device_hotplug", "cfg_hotplug_name"),
                ("options.graphics.stereo_mode_use_shared_parser", "cfg_shared_parser_name"),
            ):
                self.autoexec_widget_rows[key]["name"].configure(text=t(name_key, lang))
            self.refresh_route_tool_control()
            self.refresh_autoexec_controls()

        # Tab 6: Backups
        self.lbl_paths_title.configure(text=t("paths_title", lang))
        self.btn_autodetect.configure(text=t("btn_autodetect", lang))
        self.lbl_dcs_path.configure(text=t("dcs_path_label", lang))
        self.lbl_dcs_hint.configure(text=t("dcs_path_hint", lang))
        self.lbl_sg_path.configure(text=t("sg_path_label", lang))
        self.lbl_sg_hint.configure(text=t("sg_path_hint", lang))
        self.btn_browse_dcs.configure(text=t("btn_browse", lang))
        self.btn_browse_sg.configure(text=t("btn_browse", lang))
        self.lbl_clean_title.configure(text=t("clean_backup_title", lang))
        self.lbl_clean_desc.configure(text=t("clean_backup_desc", lang))
        self.lbl_clean_status.configure(text=t("clean_backup_status", lang))
        self.btn_restore.configure(text=t("btn_restore_clean", lang))

        # Footer
        self.btn_refresh.configure(text=t("btn_reload_files", lang))
        self.btn_apply.configure(text=t("btn_save_custom", lang))

        # Re-translate current status message
        if self.current_status_key == "preset_applied_status":
            act = self.app_settings.get("active_preset", "recommended_vr")
            p_title = get_preset_title(act, lang)
            self.status_label.configure(text=f"ℹ️ {t('preset_applied_status', lang, title=p_title)}")
        elif self.current_status_key:
            self.status_label.configure(text=f"ℹ️ {t(self.current_status_key, lang, **self.current_status_kwargs)}")

    def sync_ui_from_state(self, s: dict):
        # 1. Messages width
        w_mode = s.get("msg_width_mode", "fraction")
        self.var_width_mode.set(w_mode)
        self.on_width_mode_changed()

        frac = s.get("msg_width_fraction", "1/4")
        seg_val = t("frac_1_4", self.current_lang)
        if frac == "1/2":
            seg_val = t("frac_1_2", self.current_lang)
        elif frac == "1/3":
            seg_val = t("frac_1_3", self.current_lang)
        elif frac == "1/4":
            seg_val = t("frac_1_4", self.current_lang)
        elif frac == "1/5":
            seg_val = t("frac_1_5", self.current_lang)
        self.seg_fraction.set(seg_val)

        fixed_w = s.get("msg_width_fixed", 650)
        self.slider_fixed_w.set(fixed_w)
        self.lbl_fixed_w_val.configure(text=f"{fixed_w} px")

        # 2. Messages font & scale
        font_size = s.get("msg_hmd_font_size", 13)
        self.slider_font_size.set(font_size)
        self.lbl_font_size_val.configure(text=f"{font_size} pt")

        # 3. Radio menu
        r_scale = s.get("radio_hmd_scale", 1.1)
        self.slider_radio_scale.set(r_scale)
        self.lbl_radio_scale_val.configure(text=f"{r_scale:.2f}x")

        r_w = s.get("radio_width", 280)
        self.slider_radio_w.set(r_w)
        self.lbl_radio_w_val.configure(text=f"{r_w}")

        r_h = s.get("radio_height", 380)
        self.slider_radio_h.set(r_h)
        self.lbl_radio_h_val.configure(text=f"{r_h}")

        # 4. Options
        opt_scale = s.get("options_messages_font_scale", 1.0)
        self.slider_opt_font_scale.set(opt_scale)
        self.lbl_opt_font_scale_val.configure(text=f"{opt_scale:.2f}")

        ipd = s.get("options_custom_ipd", 63)
        self.slider_ipd.set(ipd)
        ipd_unit = " мм" if self.current_lang == "ru" else " mm"
        self.lbl_ipd_val.configure(text=f"{ipd}{ipd_unit}")

        box_cur = s.get("options_box_mouse_cursor", True)
        self.var_box_cursor.set(box_cur)
        self.update_presets_tab_display()

    def update_status_badges(self):
        """Updates header badges (DCS detected / not found, backups safe / missing) with real-time text and color."""
        lang = self.current_lang

        # 1. DCS detection status
        dcs_found = bool(self.current_live_state.get("files_found", {}).get("gameMessages_lua"))
        if dcs_found:
            self.dcs_status_badge.configure(
                text=t("status_dcs_found", lang),
                text_color=THEME["status_green_text"]
            )
        else:
            self.dcs_status_badge.configure(
                text=t("status_dcs_missing", lang),
                text_color=THEME["status_red_text"]
            )

        # 2. Backup status
        from config import ORIGINAL_BACKUPS_DIR
        has_orig_backups = ORIGINAL_BACKUPS_DIR.exists() and any(ORIGINAL_BACKUPS_DIR.glob("*.lua"))
        if has_orig_backups:
            self.backup_status_badge.configure(
                text=t("status_backup_safe", lang),
                text_color=THEME["status_green_text"]
            )
        else:
            self.backup_status_badge.configure(
                text=t("status_backup_missing", lang),
                text_color=THEME["status_amber_text"] if dcs_found else THEME["status_red_text"]
            )

        # 3. Inline path validation labels (in Paths Tab)
        if hasattr(self, "lbl_dcs_status"):
            if dcs_found:
                self.lbl_dcs_status.configure(text=t("path_valid_dcs", lang), text_color=THEME["status_green_text"])
            else:
                self.lbl_dcs_status.configure(text=t("path_invalid_dcs", lang), text_color=THEME["status_red_text"])

        if hasattr(self, "lbl_sg_status"):
            opt_found = bool(self.current_live_state.get("files_found", {}).get("options_lua"))
            if opt_found:
                self.lbl_sg_status.configure(text=t("path_valid_sg", lang), text_color=THEME["status_green_text"])
            else:
                self.lbl_sg_status.configure(text=t("path_invalid_sg", lang), text_color=THEME["status_red_text"])

    def action_refresh_live_state(self):
        self.route_tool_path = Path(self.dcs_path) / "Scripts" / "UI" / "RouteTool" / "RouteTool.lua"
        from route_tool_manager import ensure_route_tool_original_backup
        ensure_route_tool_original_backup(self.route_tool_path)
        from scene_vr_manager import ensure_scene_vr_backup
        ensure_scene_vr_backup(self.target_files)
        self.current_live_state = read_current_state(self.target_files)
        self.working_state = self.current_live_state.copy()
        self.sync_ui_from_state(self.working_state)
        self.update_status_badges()
        self.update_status_by_key("status_reloaded")
        if hasattr(self, "var_scene_mode"):
            from scene_vr_manager import detect_scene_vr_mode
            self.var_scene_mode.set(detect_scene_vr_mode(self.target_files))
            self.refresh_scene_original_control()
            self.update_scene_vr_badge()
        if hasattr(self, "autoexec_widget_rows"):
            self.refresh_autoexec_controls()
        if hasattr(self, "switch_route_tool"):
            self.refresh_route_tool_control()

    def action_one_click_reapply(self):
        """One-click apply after game update: loads the target preset or saved custom profile and writes to DCS."""
        active_preset = self.app_settings.get("active_preset", "custom")
        if active_preset in PRESETS:
            profile = PRESETS[active_preset]["settings"]
            ready, error = self._preflight_builtin_options()
            if not ready:
                self.show_dark_error(
                    t("dialog_error_title", self.current_lang),
                    t("builtin_preset_originals_error", self.current_lang, error=error)
                )
                return
            option_files, option_errors = self._restore_builtin_options()
            if option_errors:
                if option_files:
                    self._sync_builtin_option_ui()
                err_str = "\n".join(f"• {error}" for error in option_errors)
                self.show_dark_error(
                    t("dialog_error_title", self.current_lang),
                    t("dialog_error_apply", self.current_lang, errors=err_str)
                )
                return
        else:
            profile = self.app_settings.get("saved_custom_profile")
            if not profile:
                self.show_dark_info(
                    t("dialog_no_custom_title", self.current_lang),
                    t("dialog_no_custom_msg", self.current_lang)
                )
                return

        self.working_state.update(profile)
        self.sync_ui_from_state(self.working_state)

        success, updated_files, errors = apply_settings(self.target_files, self.working_state)
        if active_preset in PRESETS:
            updated_files.extend(option_files)
            self._sync_builtin_option_ui()
        else:
            option_files, option_errors = self.apply_custom_profile_options(profile)
            updated_files.extend(option_files)
            errors.extend(option_errors)
        if success:
            self.current_live_state = read_current_state(self.target_files)
            self.update_presets_tab_display()
            if errors:
                err_str = "\n".join(f"• {error}" for error in errors)
                msg = t("dialog_error_apply", self.current_lang, errors=err_str)
                self.show_dark_error(t("dialog_error_title", self.current_lang), msg)
            elif updated_files:
                files_str = "\n".join(f"• {f}" for f in updated_files)
                msg = t("dialog_reapply_msg", self.current_lang, count=len(updated_files), files=files_str)
                self.show_dark_info(t("dialog_success_title", self.current_lang), msg)
            else:
                self.show_dark_info(
                    t("dialog_success_title", self.current_lang),
                    t("dialog_reapply_unchanged", self.current_lang)
                )
            self.update_status_by_key("status_ready")
        else:
            err_str = "\n".join(f"• {e}" for e in errors)
            msg = t("dialog_error_apply", self.current_lang, errors=err_str)
            self.show_dark_error(t("dialog_error_title", self.current_lang), msg)

    def action_restore_clean(self):
        if not self.show_dark_askyesno(
            t("dialog_confirm_title", self.current_lang),
            t("dialog_restore_confirm", self.current_lang)
        ):
            return

        success, restored = restore_clean_original(self.target_files)
        errors = []
        if not success:
            errors.append(t("dialog_restore_standard_error", self.current_lang))

        from route_tool_manager import RouteToolError, restore_route_tool_original
        try:
            if restore_route_tool_original(self.route_tool_path):
                restored.append("RouteTool.lua")
        except (OSError, RouteToolError) as error:
            errors.append(t("dialog_restore_route_error", self.current_lang, error=str(error)))

        self.action_refresh_live_state()
        if errors:
            self.show_dark_error(
                t("dialog_error_title", self.current_lang),
                t("dialog_restore_error", self.current_lang, errors="\n".join(f"• {error}" for error in errors))
            )
        else:
            self.show_dark_info(
                t("dialog_success_title", self.current_lang),
                t("dialog_restore_success", self.current_lang, count=len(restored))
            )
            self.update_status_by_key("status_ready")

    def on_close(self):
        try:
            if self.state() != "iconic":
                curr_w = self.winfo_width()
                curr_h = self.winfo_height()
                if curr_w >= 800 and curr_h >= 600:
                    self.app_settings["window_width"] = curr_w
                    self.app_settings["window_height"] = curr_h
                    save_settings(self.app_settings)
        except Exception as e:
            print(f"Error persisting window dimensions: {e}")
        self.destroy()

def main():
    app = DcsVrUiEditorApp()
    app.mainloop()

if __name__ == "__main__":
    main()
