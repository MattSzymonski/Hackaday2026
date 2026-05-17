"""File explorer app for the badge."""

import os

import lvgl

from apps.base_app import BaseApp
from ui.page import Page
from ui.page import SCREEN_HEIGHT, SCREEN_WIDTH, MENU_HEIGHT, INFOBAR_HEIGHT
import ui.styles as styles

# Row height — montserrat_12 renders at 12px glyph + ~4px line-gap = 16px per row
_ROW_H = 16
# Scrollbar strip width in pixels
_SCROLLBAR_W = 4
# Visible rows: (screen - infobar - menubar - infobar_y_offset) // row_height, minus 1 for safety
# The infobar uses align(TOP_LEFT, 0, 5) which in flex layout creates a ~5px gap eating into space.
_VISIBLE_ROWS = max(1, (SCREEN_HEIGHT - INFOBAR_HEIGHT - MENU_HEIGHT - 5) // _ROW_H)

# Icons — prefer LVGL built-in symbols, fall back to ASCII
try:
    _ICON_DIR  = lvgl.SYMBOL.DIRECTORY + " "
    _ICON_FILE = lvgl.SYMBOL.FILE + " "
except AttributeError:
    try:
        _ICON_DIR  = lvgl.SYMBOL.FOLDER + " "
        _ICON_FILE = lvgl.SYMBOL.FILE + " "
    except AttributeError:
        _ICON_DIR  = "[/] "
        _ICON_FILE = "[-] "


class App(BaseApp):
    """Simple file-explorer: browse directories, enter folders with Enter, go up with Backspace/Left/F1."""

    def __init__(self, name: str, badge):
        super().__init__(name, badge)
        self.foreground_sleep_ms = 80
        self.background_sleep_ms = 2000

        self.pwd = "/"
        self.entries = []        # list of (name, is_dir) for current directory
        self.selection = 0       # index into self.entries
        self._scroll_offset = 0  # index of first visible row
        self.p = None
        self._row_labels = []     # lvgl label objects for currently visible rows
        self._scrollbar_track = None
        self._scrollbar_thumb = None

    # ------------------------------------------------------------------
    # App lifecycle
    # ------------------------------------------------------------------

    def switch_to_foreground(self):
        super().switch_to_foreground()
        self._build_screen()

    def switch_to_background(self):
        self.p = None
        self._row_labels = []
        super().switch_to_background()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_foreground(self):
        kb = self.badge.keyboard
        key = kb.read_key()
        # UP/DOWN are handled via held state for continuous scroll;
        # drain button-press events from the key buffer to avoid double-moves.
        if key in (kb.UP, kb.DOWN):
            key = None

        moved = False
        if kb.up_held:
            if self.selection > 0:
                self.selection -= 1
                moved = True
        elif kb.down_held:
            if self.selection < len(self.entries) - 1:
                self.selection += 1
                moved = True

        if moved:
            self._update_scroll()
            self._render_list()
            return

        if key == kb.ENTER or key == kb.RIGHT:
            self._enter_selection()
        elif key == kb.BS or key == kb.LEFT:
            self._go_up()
        elif kb.f1():
            if self.pwd != "/":
                self._go_up()
        elif kb.f5():
            self.badge.display.clear()
            self.switch_to_background()

    # ------------------------------------------------------------------
    # Navigation helpers
    # ------------------------------------------------------------------

    def _enter_selection(self):
        if not self.entries:
            return
        name, is_dir = self.entries[self.selection]
        if is_dir:
            self.pwd = self.pwd.rstrip("/") + "/" + name
            self.selection = 0
            self._scroll_offset = 0
            self._build_screen()

    def _go_up(self):
        if self.pwd == "/":
            return
        parent = self.pwd.rsplit("/", 1)[0]
        self.pwd = parent if parent else "/"
        self.selection = 0
        self._scroll_offset = 0
        self._build_screen()

    # ------------------------------------------------------------------
    # Screen building
    # ------------------------------------------------------------------

    def _load_entries(self):
        """Read current directory; sort folders first, then files, both alphabetically."""
        try:
            raw = os.listdir(self.pwd)
        except Exception as e:
            print("Files: listdir error:", e)
            raw = []
        dirs = []
        files = []
        for name in raw:
            path = self.pwd.rstrip("/") + "/" + name
            try:
                is_dir = bool(os.stat(path)[0] & 0x4000)
            except Exception:
                is_dir = False
            if is_dir:
                dirs.append((name, True))
            else:
                files.append((name, False))
        dirs.sort(key=lambda x: x[0])
        files.sort(key=lambda x: x[0])
        self.entries = dirs + files

    def _build_screen(self):
        """(Re-)build the full LVGL screen for the current directory."""
        self._load_entries()

        self.p = Page()
        self.p.create_infobar(["Files | pwd: " + self.pwd])
        self.p.create_content()

        if self.pwd == "/":
            self.p.create_menubar(["", "", "", "", "Exit"])
        else:
            self.p.create_menubar(["Back", "", "", "", "Exit"])
        # Eliminate flex row-gap and content internal padding (prevent black bar + clipping).
        self.p.flex_container.set_style_pad_row(0, 0)
        self.p.flex_container.set_style_pad_column(0, 0)
        self.p.content.set_style_pad_all(0, 0)

        # Scrollbar track (grey background strip on right edge)
        self._scrollbar_track = lvgl.obj(self.p.content)
        self._scrollbar_track.set_style_bg_color(styles.hackaday_grey, 0)
        self._scrollbar_track.set_style_bg_opa(255, 0)
        self._scrollbar_track.set_style_border_width(0, 0)
        self._scrollbar_track.set_style_radius(2, 0)
        self._scrollbar_track.set_size(_SCROLLBAR_W, _VISIBLE_ROWS * _ROW_H)
        self._scrollbar_track.set_pos(SCREEN_WIDTH - _SCROLLBAR_W - 2, 0)

        # Scrollbar thumb (green, position/size updated by _render_scrollbar)
        self._scrollbar_thumb = lvgl.obj(self.p.content)
        self._scrollbar_thumb.set_style_bg_color(styles.lcd_color_fg, 0)
        self._scrollbar_thumb.set_style_bg_opa(255, 0)
        self._scrollbar_thumb.set_style_border_width(0, 0)
        self._scrollbar_thumb.set_style_radius(2, 0)
        self._scrollbar_thumb.set_size(_SCROLLBAR_W, 4)
        self._scrollbar_thumb.set_pos(SCREEN_WIDTH - _SCROLLBAR_W - 2, 0)

        self._row_labels = []
        self._render_list()
        self.p.replace_screen()

    def _update_scroll(self):
        """Adjust _scroll_offset so the selected row stays in the visible window."""
        if self.selection < self._scroll_offset:
            self._scroll_offset = self.selection
        elif self.selection >= self._scroll_offset + _VISIBLE_ROWS:
            self._scroll_offset = self.selection - _VISIBLE_ROWS + 1

    def _render_list(self):
        """Render only the visible window of entries, replacing existing labels."""
        for lbl in self._row_labels:
            try:
                lbl.delete()
            except Exception:
                pass
        self._row_labels = []

        visible = self.entries[self._scroll_offset : self._scroll_offset + _VISIBLE_ROWS]

        for slot, (name, is_dir) in enumerate(visible):
            abs_idx = self._scroll_offset + slot
            icon = _ICON_DIR if is_dir else _ICON_FILE
            text = icon + name

            lbl = lvgl.label(self.p.content)
            lbl.set_style_text_font(lvgl.font_montserrat_12, 0)
            lbl.set_pos(2, slot * _ROW_H)

            if abs_idx == self.selection:
                lbl.set_style_bg_color(styles.lcd_color_fg, 0)
                lbl.set_style_bg_opa(255, 0)
                lbl.set_style_text_color(styles.lcd_color_bg, 0)
            else:
                lbl.set_style_bg_opa(0, 0)
                lbl.set_style_text_color(styles.lcd_color_fg, 0)

            lbl.set_text(text)
            self._row_labels.append(lbl)

        self._render_scrollbar()

    def _render_scrollbar(self):
        """Update scrollbar thumb position and size to reflect current viewport."""
        if self._scrollbar_track is None:
            return
        total = len(self.entries)
        track_h = _VISIBLE_ROWS * _ROW_H
        if total <= _VISIBLE_ROWS:
            # All entries fit — full-height thumb (no scrolling needed)
            self._scrollbar_thumb.set_size(_SCROLLBAR_W, track_h)
            self._scrollbar_thumb.set_pos(SCREEN_WIDTH - _SCROLLBAR_W - 2, 0)
            return
        thumb_h = max(4, track_h * _VISIBLE_ROWS // total)
        thumb_y = (track_h - thumb_h) * self._scroll_offset // (total - _VISIBLE_ROWS)
        self._scrollbar_thumb.set_size(_SCROLLBAR_W, thumb_h)
        self._scrollbar_thumb.set_pos(SCREEN_WIDTH - _SCROLLBAR_W - 2, thumb_y)
