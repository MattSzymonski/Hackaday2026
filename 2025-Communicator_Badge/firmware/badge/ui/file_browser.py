"""Reusable file-browser widget for LVGL-based badge apps.

Example usage::

    from ui.file_browser import FileBrowser
    from ui.page import SCREEN_HEIGHT, MENU_HEIGHT, INFOBAR_HEIGHT

    visible_rows = max(1, (SCREEN_HEIGHT - INFOBAR_HEIGHT - MENU_HEIGHT - 5) // 16)
    browser = FileBrowser(some_lvgl_container, visible_rows)

    # Navigation (call from your run_foreground loop):
    browser.move_up()        # move selection up, returns True if moved
    browser.move_down()      # move selection down, returns True if moved
    browser.enter()          # enter selected directory, returns True if navigated
    browser.go_up()          # go to parent directory, returns True if navigated

    # State queries:
    browser.pwd              # current directory path string
    browser.selected_entry   # (name, is_dir) tuple or None
    browser.selected_path    # full path to the highlighted item
"""

import os

import lvgl

from ui.page import SCREEN_WIDTH
import ui.styles as styles

_ROW_H_DEFAULT = 16
_SCROLLBAR_W_DEFAULT = 4

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


class FileBrowser:
    """Scrollable, keyboard-driven file-browser widget.

    Renders a directory listing with a scrollbar into *container* (any
    ``lvgl.obj``).  The caller is responsible for screen layout; this class
    only manages the content area it is given.

    Parameters
    ----------
    container:
        LVGL object to render into.
    visible_rows:
        Number of rows that fit in the container.
    row_h:
        Pixel height of each row (default 16, matches montserrat_12).
    scrollbar_w:
        Width in pixels of the scrollbar strip (default 4).
    """

    # Frames of up/down held before repeat scrolling begins (~320 ms at 80 ms/frame).
    HOLD_DELAY = 4

    def __init__(self, container, visible_rows,
                 row_h=_ROW_H_DEFAULT, scrollbar_w=_SCROLLBAR_W_DEFAULT):
        self._container = container
        self._visible_rows = visible_rows
        self._row_h = row_h
        self._scrollbar_w = scrollbar_w

        self._pwd = "/"
        self._entries = []        # list of (name, is_dir)
        self._selection = 0
        self._scroll_offset = 0
        self._row_labels = []
        self._scrollbar_track = None
        self._scrollbar_thumb = None

        self._up_frames = 0    # held-scroll debounce counters
        self._down_frames = 0

        self._setup_scrollbar()
        self._load_entries()
        self._render_list()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def pwd(self):
        """Current directory path string."""
        return self._pwd

    @property
    def selected_entry(self):
        """``(name, is_dir)`` for the highlighted item, or ``None`` if empty."""
        if not self._entries:
            return None
        return self._entries[self._selection]

    @property
    def selected_path(self):
        """Full filesystem path of the highlighted item."""
        e = self.selected_entry
        if e is None:
            return self._pwd
        return self._pwd.rstrip("/") + "/" + e[0]

    def load(self, path):
        """Navigate to *path*, reset selection, and re-render."""
        self._pwd = path
        self._selection = 0
        self._scroll_offset = 0
        self._load_entries()
        self._render_list()

    def move_up(self):
        """Move selection up by one row.  Returns ``True`` if selection changed."""
        if self._selection > 0:
            self._selection -= 1
            self._update_scroll()
            self._render_list()
            return True
        return False

    def move_down(self):
        """Move selection down by one row.  Returns ``True`` if selection changed."""
        if self._selection < len(self._entries) - 1:
            self._selection += 1
            self._update_scroll()
            self._render_list()
            return True
        return False

    def tick(self, up_held, down_held):
        """Call once per frame with held-key states.  Moves selection with a hold
        delay so a quick tap moves exactly one row instead of N frames worth.
        Returns ``True`` if selection moved."""
        if up_held:
            self._up_frames += 1
            self._down_frames = 0
            if self._up_frames == 1 or self._up_frames > self.HOLD_DELAY:
                return self.move_up()
        elif down_held:
            self._down_frames += 1
            self._up_frames = 0
            if self._down_frames == 1 or self._down_frames > self.HOLD_DELAY:
                return self.move_down()
        else:
            self._up_frames = 0
            self._down_frames = 0
        return False

    def enter(self):
        """Enter the currently selected directory.  Returns ``True`` if navigated."""
        e = self.selected_entry
        if e is None:
            return False
        name, is_dir = e
        if not is_dir:
            return False
        self.load(self._pwd.rstrip("/") + "/" + name)
        return True

    def go_up(self):
        """Navigate to the parent directory.  Returns ``True`` if navigated."""
        if self._pwd == "/":
            return False
        parent = self._pwd.rsplit("/", 1)[0]
        self.load(parent if parent else "/")
        return True

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_entries(self):
        try:
            raw = os.listdir(self._pwd)
        except Exception as exc:
            print("FileBrowser: listdir error:", exc)
            raw = []
        dirs = []
        files = []
        for name in raw:
            path = self._pwd.rstrip("/") + "/" + name
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
        self._entries = dirs + files

    def _setup_scrollbar(self):
        track_h = self._visible_rows * self._row_h
        sw = self._scrollbar_w
        x = SCREEN_WIDTH - sw - 2

        self._scrollbar_track = lvgl.obj(self._container)
        self._scrollbar_track.set_style_bg_color(styles.hackaday_grey, 0)
        self._scrollbar_track.set_style_bg_opa(255, 0)
        self._scrollbar_track.set_style_border_width(0, 0)
        self._scrollbar_track.set_style_radius(2, 0)
        self._scrollbar_track.set_size(sw, track_h)
        self._scrollbar_track.set_pos(x, 0)

        self._scrollbar_thumb = lvgl.obj(self._container)
        self._scrollbar_thumb.set_style_bg_color(styles.lcd_color_fg, 0)
        self._scrollbar_thumb.set_style_bg_opa(255, 0)
        self._scrollbar_thumb.set_style_border_width(0, 0)
        self._scrollbar_thumb.set_style_radius(2, 0)
        self._scrollbar_thumb.set_size(sw, 4)
        self._scrollbar_thumb.set_pos(x, 0)

    def _update_scroll(self):
        if self._selection < self._scroll_offset:
            self._scroll_offset = self._selection
        elif self._selection >= self._scroll_offset + self._visible_rows:
            self._scroll_offset = self._selection - self._visible_rows + 1

    def _render_list(self):
        for lbl in self._row_labels:
            try:
                lbl.delete()
            except Exception:
                pass
        self._row_labels = []

        visible = self._entries[self._scroll_offset : self._scroll_offset + self._visible_rows]

        for slot, (name, is_dir) in enumerate(visible):
            abs_idx = self._scroll_offset + slot
            icon = _ICON_DIR if is_dir else _ICON_FILE

            lbl = lvgl.label(self._container)
            lbl.set_style_text_font(lvgl.font_montserrat_12, 0)
            lbl.set_pos(2, slot * self._row_h)

            if abs_idx == self._selection:
                lbl.set_style_bg_color(styles.lcd_color_fg, 0)
                lbl.set_style_bg_opa(255, 0)
                lbl.set_style_text_color(styles.lcd_color_bg, 0)
            else:
                lbl.set_style_bg_opa(0, 0)
                lbl.set_style_text_color(styles.lcd_color_fg, 0)

            lbl.set_text(icon + name)
            self._row_labels.append(lbl)

        self._render_scrollbar()

    def _render_scrollbar(self):
        if self._scrollbar_thumb is None:
            return
        total = len(self._entries)
        track_h = self._visible_rows * self._row_h
        sw = self._scrollbar_w
        x = SCREEN_WIDTH - sw - 2
        if total <= self._visible_rows:
            self._scrollbar_thumb.set_size(sw, track_h)
            self._scrollbar_thumb.set_pos(x, 0)
            return
        thumb_h = max(4, track_h * self._visible_rows // total)
        thumb_y = (track_h - thumb_h) * self._scroll_offset // (total - self._visible_rows)
        self._scrollbar_thumb.set_size(sw, thumb_h)
        self._scrollbar_thumb.set_pos(x, thumb_y)
