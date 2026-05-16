"""App that displays 'Unreal SUCKS!' on the screen."""

import lvgl

from apps.base_app import BaseApp
from ui.page import Page

APP_NAME = "UnrealSUCKS"


class App(BaseApp):

    def __init__(self, name: str, badge):
        super().__init__(name, badge)
        self.page = None

    def switch_to_foreground(self):
        super().switch_to_foreground()
        self.page = Page()
        self.page.create_infobar(["Unreal SUCKS!", ""])
        self.page.create_content()
        self.page.create_menubar(["", "", "", "", "Back"])

        label = lvgl.label(self.page.content)
        label.set_text("Unreal SUCKS!")
        label.set_style_text_font(lvgl.font_montserrat_28, 0)
        label.align(lvgl.ALIGN.CENTER, 0, 0)

        self.page.replace_screen()

    def run_foreground(self):
        if self.badge.keyboard.f5():
            self.badge.display.clear()
            self.switch_to_background()

    def switch_to_background(self):
        super().switch_to_background()
        self.page = None
