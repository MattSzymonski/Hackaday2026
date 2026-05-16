"""Rotation angle display app with manual and auto-rotation controls.

Servo wiring (Tower Pro Micro Servo 9g):
  Signal (orange/yellow) → SAO GPIO1 header pin (ESP32 GPIO7)
  VCC    (red)           → 3.3V or 5V header pin
  GND    (brown/black)   → GND header pin

The display angle (−90–+90°) maps directly to servo range (0–180°) via: servo° = display° + 90.
"""

import time
import lvgl
from machine import Pin, PWM

from apps.base_app import BaseApp
from hardware.keyboard import Keyboard
from ui.page import Page

APP_NAME = "Rooootation"

# Defaults
DEFAULT_SPEED = 30.0   # degrees per second
SPEED_STEP    = 10.0   # degrees/s per Up/Down press
ANGLE_STEP    = 5.0    # degrees per Left/Right press
ANGLE_MIN     = -90.0  # display angle minimum
ANGLE_MAX     =  90.0  # display angle maximum
MIN_SPEED     = 5.0
MAX_SPEED     = 90.0   # display degrees/s cap (equals servo physical limit)

# Servo PWM settings (Tower Pro 9g at 50 Hz)
SERVO_PIN           = 7          # SAO GPIO1
SERVO_FREQ          = 50         # Hz
SERVO_MIN_NS        = 500_000    # 0.5 ms  → 0°
SERVO_MAX_NS        = 2_500_000  # 2.5 ms  → 180°
SERVO_MAX_DEG_S     = 120.0      # max servo slew rate deg/s (conservative for loaded servo)
SERVO_TICK_S        = 0.05       # matches foreground_sleep_ms
SPEED_LIMIT         = SERVO_MAX_DEG_S        # display deg/s == servo deg/s (1:1 mapping)


class App(BaseApp):

    def __init__(self, name: str, badge):
        super().__init__(name, badge)
        self.foreground_sleep_ms = 50   # ~20 fps
        self.background_sleep_ms = 1000

        self.angle      = 0.0
        self.speed      = DEFAULT_SPEED
        self.auto       = False
        self._auto_dir  = 1            # +1 or -1, direction of auto-rotation
        self._last_tick = None
        self._last_servo_angle = None   # track last sent value, avoid redundant PWM writes
        self._servo_pos        = 0.0    # current servo position (deg, 0-180), rate-limited
        self._limiter_active   = False  # True when software speed limiter is engaging
        # Set-mode state
        self._set_mode       = False
        self._set_textarea   = None
        self._set_prompt_lbl = None
        self._set_deg_lbl    = None

        self.page          = None
        self._angle_lbl    = None
        self._speed_lbl    = None
        self._auto_lbl     = None
        self._limiter_lbl  = None
        self._arc          = None
        self._servo        = None

    # ------------------------------------------------------------------
    def switch_to_foreground(self):
        super().switch_to_foreground()
        self._last_tick = time.ticks_ms()

        # Init servo PWM
        self._servo = PWM(Pin(SERVO_PIN), freq=SERVO_FREQ)
        self._servo_pos = max(0.0, min(180.0, self.angle + 90.0))  # -90→0, 0→90, +90→180
        self._servo_write_deg(self._servo_pos)
        self._last_servo_angle = int(self._servo_pos)

        self.page = Page()
        self.page.create_infobar(["Rotation", ""])
        self.page.create_content()
        self.page.create_menubar(["Set", "Spd-", "R:Auto", "Spd+", "Back"])

        content = self.page.content

        # Arc widget — semicircle from left (-90°) through top (0°) to right (+90°)
        self._arc = lvgl.arc(content)
        self._arc.set_size(90, 90)
        self._arc.set_range(-90, 90)
        self._arc.set_bg_angles(180, 360)   # top half: 180°=left, 270°=top/0°, 360°=right
        self._arc.set_value(int(self.angle))
        self._arc.remove_style(None, lvgl.PART.KNOB)   # hide knob
        self._arc.align(lvgl.ALIGN.LEFT_MID, 10, 0)

        # Large angle label
        self._angle_lbl = lvgl.label(content)
        self._angle_lbl.set_style_text_font(lvgl.font_montserrat_28, 0)
        self._angle_lbl.align(lvgl.ALIGN.CENTER, 10, -18)
        self._angle_lbl.set_text(self._angle_str())

        # Speed label
        self._speed_lbl = lvgl.label(content)
        self._speed_lbl.set_style_text_font(lvgl.font_montserrat_16, 0)
        self._speed_lbl.align(lvgl.ALIGN.CENTER, 10, 14)
        self._speed_lbl.set_text(self._speed_str())

        # Auto-rotate status label
        self._auto_lbl = lvgl.label(content)
        self._auto_lbl.set_style_text_font(lvgl.font_montserrat_16, 0)
        self._auto_lbl.align(lvgl.ALIGN.CENTER, 10, 34)
        self._auto_lbl.set_text(self._auto_str())

        # Software limiter indicator (shown when limiter is active)
        self._limiter_lbl = lvgl.label(content)
        self._limiter_lbl.set_style_text_font(lvgl.font_montserrat_14, 0)
        self._limiter_lbl.set_style_text_color(lvgl.color_make(255, 80, 0), 0)
        self._limiter_lbl.align(lvgl.ALIGN.CENTER, 10, 52)
        self._limiter_lbl.set_text("LIMITER" if self._limiter_active else "")

        self.page.replace_screen()

    # ------------------------------------------------------------------
    def run_foreground(self):
        kbd = self.badge.keyboard

        # --- Set mode input ---
        if self._set_mode:
            key = kbd.read_key()
            if key is not None:
                txt = self._set_textarea.get_text()
                if key == Keyboard.BS:
                    self._set_textarea.delete_char()
                elif key == Keyboard.ENTER:
                    self._exit_set_mode(apply=True)
                    return
                elif key == '-' and len(txt) == 0:
                    self._set_textarea.add_text('-')
                elif key in '0123456789' and len(txt.replace('-', '')) < 3:
                    self._set_textarea.add_text(key)
            if kbd.f5():
                self._exit_set_mode(apply=False)
            return

        # --- Continuous rotation tick ---
        now = time.ticks_ms()
        if self._last_tick is not None and self.auto:
            dt = time.ticks_diff(now, self._last_tick) / 1000.0
            new_angle = self.angle + self._auto_dir * self.speed * dt
            if new_angle >= ANGLE_MAX:
                new_angle = ANGLE_MAX
                self._auto_dir = -1   # bounce back
            elif new_angle <= ANGLE_MIN:
                new_angle = ANGLE_MIN
                self._auto_dir = 1    # bounce forward
            self.angle = new_angle
        self._last_tick = now

        # --- Key handling ---
        key = kbd.read_key()
        changed = False

        # F1=Set, F2=Spd-, F3=R:Auto, F4=Spd+
        if kbd.f1():
            self._enter_set_mode()
            return
        elif kbd.left_held:
            self.angle = max(ANGLE_MIN, self.angle - ANGLE_STEP)
            changed = True
        elif kbd.f2() or key == Keyboard.DOWN:
            self.speed = max(MIN_SPEED, self.speed - SPEED_STEP)
            changed = True
        elif kbd.f3() or key == "r" or key == "R":
            self.auto = not self.auto
            changed = True
        elif kbd.f4() or key == Keyboard.UP:
            if self.speed < SPEED_LIMIT:
                self.speed = min(SPEED_LIMIT, self.speed + SPEED_STEP)
            changed = True  # always redraw so limiter label updates
        elif kbd.right_held:
            self.angle = min(ANGLE_MAX, self.angle + ANGLE_STEP)
            changed = True

        # Always update display when auto-rotating, otherwise only on change
        if self.auto or changed:
            # Rate-limited servo update: step servo_pos toward target each tick
            target = self.angle + 90.0   # -90→ 0, 0→90, +90→180
            max_step = SERVO_MAX_DEG_S * SERVO_TICK_S
            diff = target - self._servo_pos
            if abs(diff) > 0.5:  # ignore sub-0.5° differences
                step = max(-max_step, min(max_step, diff))
                self._servo_pos += step
                self._servo_pos = max(0.0, min(180.0, self._servo_pos))
                self._limiter_active = (abs(diff) > max_step) or (self.speed >= SPEED_LIMIT)
                new_int = int(self._servo_pos)
                if new_int != self._last_servo_angle:
                    self._servo_write_deg(self._servo_pos)
                    self._last_servo_angle = new_int
            else:
                self._limiter_active = (self.speed >= SPEED_LIMIT)
            self._update_display()

        # F5 — back
        if kbd.f5():
            self.switch_to_background()

    # ------------------------------------------------------------------
    def switch_to_background(self):
        self.auto = False
        self._set_mode = False
        self._set_textarea   = None
        self._set_prompt_lbl = None
        self._set_deg_lbl    = None
        # Deinit servo to stop PWM signal and free the pin
        if self._servo is not None:
            try:
                self._servo.deinit()
            except Exception:
                pass
            self._servo = None
        self._last_servo_angle = None
        self.page          = None
        self._angle_lbl    = None
        self._speed_lbl    = None
        self._auto_lbl     = None
        self._limiter_lbl  = None
        self._arc          = None
        super().switch_to_background()

    # ------------------------------------------------------------------
    def _enter_set_mode(self):
        """Enter direct angle-value entry mode."""
        self._set_mode = True
        self.auto = False

        # Hide main content widgets
        for w in (self._arc, self._angle_lbl, self._speed_lbl, self._auto_lbl, self._limiter_lbl):
            if w:
                w.add_flag(lvgl.OBJ_FLAG.HIDDEN)

        # Update menubar
        self.page.set_menubar_button_label(0, "")
        self.page.set_menubar_button_label(1, "")
        self.page.set_menubar_button_label(2, "")
        self.page.set_menubar_button_label(3, "")
        self.page.set_menubar_button_label(4, "Cancel")

        content = self.page.content

        self._set_prompt_lbl = lvgl.label(content)
        self._set_prompt_lbl.set_style_text_font(lvgl.font_montserrat_16, 0)
        self._set_prompt_lbl.align(lvgl.ALIGN.CENTER, 0, -22)
        self._set_prompt_lbl.set_text("Enter angle value:")

        self._set_textarea = lvgl.textarea(content)
        self._set_textarea.set_one_line(True)
        self._set_textarea.set_width(80)
        self._set_textarea.set_height(30)
        self._set_textarea.set_text("")
        self._set_textarea.align(lvgl.ALIGN.CENTER, -20, 8)
        self._set_textarea.add_state(lvgl.STATE.FOCUSED)

        self._set_deg_lbl = lvgl.label(content)
        self._set_deg_lbl.set_style_text_font(lvgl.font_montserrat_16, 0)
        self._set_deg_lbl.align_to(self._set_textarea, lvgl.ALIGN.OUT_RIGHT_MID, 6, 0)
        self._set_deg_lbl.set_text("deg")

    def _exit_set_mode(self, apply: bool):
        """Exit angle-setting mode, optionally applying the typed value."""
        if apply and self._set_textarea:
            try:
                raw = self._set_textarea.get_text().strip()
                val = float(raw)
                self.angle = max(ANGLE_MIN, min(ANGLE_MAX, val))
            except Exception:
                pass

        for w in (self._set_textarea, self._set_prompt_lbl, self._set_deg_lbl):
            if w:
                try:
                    w.delete()
                except Exception:
                    pass
        self._set_textarea   = None
        self._set_prompt_lbl = None
        self._set_deg_lbl    = None

        # Unhide main widgets
        for w in (self._arc, self._angle_lbl, self._speed_lbl, self._auto_lbl, self._limiter_lbl):
            if w:
                try:
                    w.clear_flag(lvgl.OBJ_FLAG.HIDDEN)
                except Exception:
                    pass

        self.page.set_menubar_button_label(0, "Set")
        self.page.set_menubar_button_label(1, "Spd-")
        self.page.set_menubar_button_label(2, "R:Auto")
        self.page.set_menubar_button_label(3, "Spd+")
        self.page.set_menubar_button_label(4, "Back")

        self._set_mode = False
        self._update_display()

    # ------------------------------------------------------------------
    def _servo_write_deg(self, deg: float):
        """Write servo position directly in degrees (0-180)."""
        pulse_ns = int(SERVO_MIN_NS + (deg / 180.0) * (SERVO_MAX_NS - SERVO_MIN_NS))
        self._servo.duty_ns(pulse_ns)

    def _servo_write(self, display_angle: float):
        """Map display angle (-90..+90) to servo range (0..180) and write PWM."""
        self._servo_write_deg(max(0.0, min(180.0, display_angle + 90.0)))

    # ------------------------------------------------------------------
    def _angle_str(self):
        return f"{self.angle:+07.2f} deg"

    def _speed_str(self):
        return f"Speed: {self.speed:.0f} deg/s"

    def _auto_str(self):
        return "Auto: ON " if self.auto else "Auto: OFF"

    def _update_display(self):
        if self._angle_lbl:
            self._angle_lbl.set_text(self._angle_str())
        if self._speed_lbl:
            self._speed_lbl.set_text(self._speed_str())
        if self._auto_lbl:
            self._auto_lbl.set_text(self._auto_str())
        if self._limiter_lbl:
            self._limiter_lbl.set_text("LIMITER" if self._limiter_active else "")
        if self._arc:
            self._arc.set_value(int(self.angle))
