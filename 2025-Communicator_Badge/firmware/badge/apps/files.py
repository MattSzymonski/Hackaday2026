"""File explorer app for the badge."""

from apps.base_app import BaseApp
from ui.page import Page
from ui.page import SCREEN_HEIGHT, MENU_HEIGHT, INFOBAR_HEIGHT
from ui.file_browser import FileBrowser

# Visible rows: (screen - infobar - menubar - 5px flex gap) // row_height, minus 1 for safety
_VISIBLE_ROWS = max(1, (SCREEN_HEIGHT - INFOBAR_HEIGHT - MENU_HEIGHT - 5) // 16)


class App(BaseApp):
    """File-explorer: browse directories with arrow keys, Enter/Right to enter, Left/Backspace/F1 to go up."""

    def __init__(self, name: str, badge):
        super().__init__(name, badge)
        self.foreground_sleep_ms = 80
        self.background_sleep_ms = 2000
        self.p = None
        self.browser = None

    # ------------------------------------------------------------------
    # App lifecycle
    # ------------------------------------------------------------------

    def switch_to_foreground(self):
        super().switch_to_foreground()
        self._build_screen()

    def switch_to_background(self):
        self.p = None
        self.browser = None
        super().switch_to_background()

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run_foreground(self):
        kb = self.badge.keyboard
        key = kb.read_key()
        # Held up/down drive continuous scroll; discard their key-buffer events.
        if key in (kb.UP, kb.DOWN):
            key = None

        if kb.up_held:
            self.browser.move_up()
        elif kb.down_held:
            self.browser.move_down()
        elif key == kb.ENTER or key == kb.RIGHT:
            if self.browser.enter():
                self._update_infobar()
        elif key == kb.BS or key == kb.LEFT:
            if self.browser.go_up():
                self._update_infobar()
        elif kb.f1():
            if self.browser.go_up():
                self._update_infobar()
        elif kb.f5():
            self.badge.display.clear()
            self.switch_to_background()

    # ------------------------------------------------------------------
    # Screen helpers
    # ------------------------------------------------------------------

    def _build_screen(self):
        self.p = Page()
        self.p.create_infobar(["Files | pwd: /"])
        self.p.create_content()
        self.p.create_menubar(["Back", "", "", "", "Exit"])
        # Eliminate flex row-gap and content internal padding (prevents black bar + clipping).
        self.p.flex_container.set_style_pad_row(0, 0)
        self.p.flex_container.set_style_pad_column(0, 0)
        self.p.content.set_style_pad_all(0, 0)
        self.browser = FileBrowser(self.p.content, _VISIBLE_ROWS)
        self._update_infobar()
        self.p.replace_screen()

    def _update_infobar(self):
        self.p.infobar_left.set_text("Files | pwd: " + self.browser.pwd)
