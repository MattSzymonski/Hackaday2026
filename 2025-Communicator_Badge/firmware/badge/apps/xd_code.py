"""XD Code — 4-state mini-IDE for the badge.

States:
  Menu   — launch screen, F1=Files, F5=Exit
  Files  — FileBrowser, Enter/Right=open file, Left/BS=up dir, F5=Menu
  Editor — lvgl.textarea, F1=Files, F2=Output, F3=Run(.py), F4=Save, F5=Menu
  Output — scrollable script output, F1=Files, F2=Editor, F5=Menu
"""

import lvgl

from apps.base_app import BaseApp
from ui.page import Page
from ui.page import SCREEN_HEIGHT, SCREEN_WIDTH, MENU_HEIGHT, INFOBAR_HEIGHT
from ui.file_browser import FileBrowser
import ui.styles as styles

APP_NAME = "XD Code"

# Application states
_STATE_MENU   = 0
_STATE_FILES  = 1
_STATE_EDITOR = 2
_STATE_OUTPUT = 3

# Layout
_ROW_H = 16
_SCROLLBAR_W = 4
_VISIBLE_ROWS = max(1, (SCREEN_HEIGHT - INFOBAR_HEIGHT - MENU_HEIGHT - 5) // _ROW_H)


class App(BaseApp):
    """XD Code: browse files, edit, run .py scripts, view output."""

    def __init__(self, name: str, badge):
        super().__init__(name, badge)
        self.foreground_sleep_ms = 80
        self.background_sleep_ms = 2000

        self._state = _STATE_MENU
        self._filepath  = None   # currently open file path
        self._files_pwd = "/"    # persists across state transitions

        self._output_lines  = []  # list of str from last run
        self._output_name   = ""  # shown in output infobar
        self._output_offset = 0   # first visible output line

        self.p = None
        self.browser = None

        self._out_row_labels = []
        self._out_scrollbar_track = None
        self._out_scrollbar_thumb = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def switch_to_foreground(self):
        super().switch_to_foreground()
        self._goto(_STATE_MENU)

    def switch_to_background(self):
        self.p = None
        self.browser = None
        self._out_row_labels = []
        self._out_scrollbar_track = None
        self._out_scrollbar_thumb = None
        super().switch_to_background()

    # ------------------------------------------------------------------
    # Main loop dispatcher
    # ------------------------------------------------------------------

    def run_foreground(self):
        if self._state == _STATE_MENU:
            self._run_menu()
        elif self._state == _STATE_FILES:
            self._run_files()
        elif self._state == _STATE_EDITOR:
            self._run_editor()
        elif self._state == _STATE_OUTPUT:
            self._run_output()

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def _goto(self, state):
        self._state = state
        self.browser = None
        self._out_row_labels = []
        if state == _STATE_MENU:
            self._build_menu()
        elif state == _STATE_FILES:
            self._build_files()
        elif state == _STATE_EDITOR:
            self._build_editor()
        elif state == _STATE_OUTPUT:
            self._build_output()

    def _apply_layout_fixes(self):
        """Zero out flex gap and content padding (prevents black bar + clipping)."""
        self.p.flex_container.set_style_pad_row(0, 0)
        self.p.flex_container.set_style_pad_column(0, 0)
        self.p.content.set_style_pad_all(0, 0)

    # ------------------------------------------------------------------
    # Menu state
    # ------------------------------------------------------------------

    def _build_menu(self):
        self.p = Page()
        self.p.create_infobar(["XD Code", ""])
        self.p.create_content()
        self.p.create_menubar(["Files", "", "", "", "Exit"])
        self._apply_layout_fixes()

        title = lvgl.label(self.p.content)
        title.set_style_text_font(lvgl.font_montserrat_16, 0)
        title.set_style_text_color(styles.lcd_color_fg, 0)
        title.set_text("XD Code")
        title.align(lvgl.ALIGN.CENTER, 0, -14)

        subtitle = lvgl.label(self.p.content)
        subtitle.set_style_text_font(lvgl.font_montserrat_12, 0)
        subtitle.set_style_text_color(styles.lcd_color_fg, 0)
        subtitle.set_text("Not great, not terrible IDE")
        subtitle.align(lvgl.ALIGN.CENTER, 0, 10)

        self.p.replace_screen()

    def _run_menu(self):
        kb = self.badge.keyboard
        if kb.f1():
            self._goto(_STATE_FILES)
        elif kb.f5():
            self.badge.display.clear()
            self.switch_to_background()

    # ------------------------------------------------------------------
    # Files state
    # ------------------------------------------------------------------

    def _build_files(self):
        self.p = Page()
        self.p.create_infobar([self._files_pwd, "XD Code"])
        self.p.create_content()
        self.p.create_menubar(["", "", "", "", "Menu"])
        self._apply_layout_fixes()

        self.browser = FileBrowser(self.p.content, _VISIBLE_ROWS)
        if self._files_pwd != "/":
            self.browser.load(self._files_pwd)
        self.p.infobar_left.set_text(self.browser.pwd)
        self.p.replace_screen()

    def _run_files(self):
        kb = self.badge.keyboard
        key = kb.read_key()
        # Drain UP/DOWN from buffer; held state drives continuous scroll.
        if key in (kb.UP, kb.DOWN):
            key = None

        if self.browser.tick(kb.up_held, kb.down_held):
            return

        if key == kb.ENTER or key == kb.RIGHT:
            entry = self.browser.selected_entry
            if entry is not None:
                name, is_dir = entry
                if is_dir:
                    self.browser.enter()
                    self._files_pwd = self.browser.pwd
                    self.p.infobar_left.set_text(self.browser.pwd)
                else:
                    self._filepath = self.browser.selected_path
                    self._goto(_STATE_EDITOR)
        elif key == kb.BS or key == kb.LEFT:
            self.browser.go_up()
            self._files_pwd = self.browser.pwd
            self.p.infobar_left.set_text(self.browser.pwd)
        elif kb.f5():
            self._goto(_STATE_MENU)

    # ------------------------------------------------------------------
    # Editor state
    # ------------------------------------------------------------------

    def _build_editor(self):
        filename = self._filepath.rsplit("/", 1)[-1] if self._filepath else "(new)"
        is_py = self._filepath is not None and self._filepath.endswith(".py")

        self.p = Page()
        self.p.create_infobar([filename, "XD Code"])
        self.p.create_content()
        self.p.create_menubar(["Files", "Output", "Run" if is_py else "", "Save", "Menu"])
        self._apply_layout_fixes()

        # Full-size multi-line textarea
        self.p.text_box = lvgl.textarea(self.p.content)
        self.p.text_box.add_style(styles.content_style, 0)
        self.p.text_box.set_width(lvgl.pct(100))
        self.p.text_box.set_height(lvgl.pct(100))
        self.p.text_box.set_style_border_width(0, 0)
        self.p.text_box.set_style_pad_all(2, 0)
        self.p.text_box.add_state(lvgl.STATE.FOCUSED)

        text = ""
        if self._filepath:
            try:
                with open(self._filepath, "r") as f:
                    text = f.read()
            except Exception as e:
                text = "# Error reading file: " + str(e)
        self.p.text_box.set_text(text)
        self.p.replace_screen()

    def _run_editor(self):
        kb = self.badge.keyboard
        key = kb.read_key()

        # Drain UP/DOWN key-buffer events; held state drives continuous cursor movement.
        if key == kb.UP or key == kb.DOWN:
            key = None

        if kb.up_held:
            self.p.text_box.cursor_up()
        elif kb.down_held:
            self.p.text_box.cursor_down()
        elif key is not None:
            if key == kb.LEFT:
                self.p.text_box.cursor_left()
            elif key == kb.RIGHT:
                self.p.text_box.cursor_right()
            elif key == kb.BS:
                self.p.text_box.delete_char()
            elif key == kb.DEL:
                self.p.text_box.delete_char_forward()
            else:
                # Includes ENTER ("\n"), regular chars, symbols, etc.
                self.p.text_box.add_text(key)

        is_py = self._filepath is not None and self._filepath.endswith(".py")
        if kb.f1():
            self._goto(_STATE_FILES)
        elif kb.f2():
            self._goto(_STATE_OUTPUT)
        elif kb.f3():
            if is_py:
                self._run_script()
        elif kb.f4():
            self._save_file()
        elif kb.f5():
            self._goto(_STATE_MENU)

    def _save_file(self):
        if not self._filepath:
            return
        try:
            text = self.p.text_box.get_text()
            with open(self._filepath, "w") as f:
                f.write(text)
        except Exception as e:
            print("XDCode save error:", e)

    def _run_script(self):
        """Auto-save, exec the script capturing output via print override, then switch to Output."""
        self._save_file()
        self._output_name = self._filepath.rsplit("/", 1)[-1] if self._filepath else "(script)"

        output_lines = []

        def _capture_print(*args, **kwargs):
            sep = kwargs.get("sep", " ")
            end = kwargs.get("end", "\n")
            line = sep.join(str(a) for a in args) + end
            # Split on newlines but keep partial lines together
            for part in line.split("\n"):
                output_lines.append(part)

        try:
            with open(self._filepath, "r") as f:
                code = f.read()
            exec(code, {"__name__": "__main__", "print": _capture_print})  # noqa: S102
        except Exception as exc:
            output_lines.append("[Error] " + str(exc))

        self._output_lines = output_lines if output_lines else ["(no output)"]
        self._output_offset = 0
        self._goto(_STATE_OUTPUT)

    # ------------------------------------------------------------------
    # Output state
    # ------------------------------------------------------------------

    def _build_output(self):
        self.p = Page()
        self.p.create_infobar([self._output_name or "(no output)", "Output"])
        self.p.create_content()
        self.p.create_menubar(["Files", "Editor", "", "", "Menu"])
        self._apply_layout_fixes()

        x = SCREEN_WIDTH - _SCROLLBAR_W - 2
        track_h = _VISIBLE_ROWS * _ROW_H

        self._out_scrollbar_track = lvgl.obj(self.p.content)
        self._out_scrollbar_track.set_style_bg_color(styles.hackaday_grey, 0)
        self._out_scrollbar_track.set_style_bg_opa(255, 0)
        self._out_scrollbar_track.set_style_border_width(0, 0)
        self._out_scrollbar_track.set_style_radius(2, 0)
        self._out_scrollbar_track.set_size(_SCROLLBAR_W, track_h)
        self._out_scrollbar_track.set_pos(x, 0)

        self._out_scrollbar_thumb = lvgl.obj(self.p.content)
        self._out_scrollbar_thumb.set_style_bg_color(styles.lcd_color_fg, 0)
        self._out_scrollbar_thumb.set_style_bg_opa(255, 0)
        self._out_scrollbar_thumb.set_style_border_width(0, 0)
        self._out_scrollbar_thumb.set_style_radius(2, 0)
        self._out_scrollbar_thumb.set_size(_SCROLLBAR_W, 4)
        self._out_scrollbar_thumb.set_pos(x, 0)

        self._out_row_labels = []
        self._render_output()
        self.p.replace_screen()

    def _render_output(self):
        for lbl in self._out_row_labels:
            try:
                lbl.delete()
            except Exception:
                pass
        self._out_row_labels = []

        visible = self._output_lines[self._output_offset : self._output_offset + _VISIBLE_ROWS]
        label_w = SCREEN_WIDTH - _SCROLLBAR_W - 6
        for slot, line in enumerate(visible):
            lbl = lvgl.label(self.p.content)
            lbl.set_style_text_font(lvgl.font_montserrat_12, 0)
            lbl.set_style_text_color(styles.lcd_color_fg, 0)
            lbl.set_pos(2, slot * _ROW_H)
            lbl.set_width(label_w)
            lbl.set_text(line)
            self._out_row_labels.append(lbl)

        self._render_output_scrollbar()

    def _render_output_scrollbar(self):
        if self._out_scrollbar_thumb is None:
            return
        total = len(self._output_lines)
        track_h = _VISIBLE_ROWS * _ROW_H
        x = SCREEN_WIDTH - _SCROLLBAR_W - 2
        if total <= _VISIBLE_ROWS:
            self._out_scrollbar_thumb.set_size(_SCROLLBAR_W, track_h)
            self._out_scrollbar_thumb.set_pos(x, 0)
            return
        thumb_h = max(4, track_h * _VISIBLE_ROWS // total)
        thumb_y = (track_h - thumb_h) * self._output_offset // (total - _VISIBLE_ROWS)
        self._out_scrollbar_thumb.set_size(_SCROLLBAR_W, thumb_h)
        self._out_scrollbar_thumb.set_pos(x, thumb_y)

    def _run_output(self):
        kb = self.badge.keyboard
        total = len(self._output_lines)
        max_offset = max(0, total - _VISIBLE_ROWS)

        moved = False
        if kb.up_held:
            if self._output_offset > 0:
                self._output_offset -= 1
                moved = True
        elif kb.down_held:
            if self._output_offset < max_offset:
                self._output_offset += 1
                moved = True
        if moved:
            self._render_output()
            return

        if kb.f1():
            self._goto(_STATE_FILES)
        elif kb.f2():
            self._goto(_STATE_EDITOR)
        elif kb.f5():
            self._goto(_STATE_MENU)
