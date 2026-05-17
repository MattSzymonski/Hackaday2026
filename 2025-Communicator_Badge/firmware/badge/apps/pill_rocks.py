"""App that displays the PillEngine logo image on the screen."""

import lvgl

from apps.base_app import BaseApp
from ui.page import Page
from ui import graphics

APP_NAME = "Pill"

class App(BaseApp):

    def __init__(self, name: str, badge):
        super().__init__(name, badge)
        self.page = None

    def switch_to_foreground(self):
        super().switch_to_foreground()
        self.page = Page()
        self.page.create_infobar(["", ""])
        self.page.create_content()
        self.page.create_menubar(["", "", "", "", "Back"])

        img = graphics.create_image("images/pill_logo_white.png", self.page.content)
        img.align(lvgl.ALIGN.CENTER, 0, 0)

        self.page.replace_screen()

    def run_foreground(self):
        if self.badge.keyboard.f5():
            self.badge.display.clear()
            self.switch_to_background()

    def switch_to_background(self):
        super().switch_to_background()
        self.page = None
