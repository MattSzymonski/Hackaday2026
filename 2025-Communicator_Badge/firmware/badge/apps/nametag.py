"""Template app for badge applications. Copy this file and update to implement your own app."""

import uasyncio as aio  # type: ignore

from apps.base_app import BaseApp
from net.net import register_receiver, send, BROADCAST_ADDRESS
from net.protocols import Protocol, NetworkFrame
from ui.page import Page
import ui.styles as styles
import lvgl
import os
import urandom
import uctypes
from ui import graphics

"""
All protocols must be defined in their apps with unique ports. Ports must fit in uint8.
Try to pick a protocol ID that isn't in use yet; good luck.
Structdef is the struct library format string. This is a subset of cpython struct.
https://docs.micropython.org/en/latest/library/struct.html
"""
# NEW_PROTOCOL = Protocol(port=<PORT>, name="<NAME>", structdef="!")

# ---------------------------------------------------------------------------
# Glitch effect configuration
# ---------------------------------------------------------------------------
# Screen physical dimensions (pixels, after display rotation)
_GLITCH_SCREEN_W = 428
_GLITCH_SCREEN_H = 142

# How many pixels to shift the glitched band to the right
_GLITCH_SHIFT_PX = 35

# Randomised height of each glitch band (pixels)
_GLITCH_BAND_H_MIN = 15
_GLITCH_BAND_H_MAX = 50

# How many run_foreground frames the glitch is visible (each frame ~100 ms)
_GLITCH_FRAMES_MIN = 1   # ~200 ms
_GLITCH_FRAMES_MAX = 5   # ~600 ms

# How many frames of quiet between glitches
_GLITCH_COOLDOWN_MIN = 10  # ~1 s
_GLITCH_COOLDOWN_MAX = 30  # ~4 s
# ---------------------------------------------------------------------------


class App(BaseApp):
    """Define a new app to run on the badge."""

    def __init__(self, name: str, badge):
        """Define any attributes of the class in here, after super().__init__() is called.
        self.badge will be available in the rest of the class methods for accessing the badge hardware.
        If you don't have anything else to add, you can delete this method.
        """
        super().__init__(name, badge)
        # You can also set the sleep time when running in the foreground or background. Uncomment and update.
        # Remember to make background sleep longer so this app doesn't interrupt other processing.
        # self.foreground_sleep_ms = 10
        # self.background_sleep_ms = 1000
        self.username = self.badge.config.get("nametag").decode().strip()
        # Nametag image configuration
        try:
            self.show_image = self.badge.config.get("nametag_show_image").decode().strip() in ("true", "True")
        except Exception:
            self.show_image = False
        try:
            self.image_path = self.badge.config.get("nametag_image").decode().strip()
        except Exception:
            self.image_path = "images/headshots/wrencher.png"
        self.font = (
            lvgl.font_montserrat_42
        )  ## LVGL font object -- get more below or define your own
        self.all_fonts = {
            "Monserrat 48": lvgl.font_montserrat_48,
            "Monserrat ": lvgl.font_montserrat_42,
            "Monserrat 28": lvgl.font_montserrat_28,
        }
        # Image picker state
        self.image_dir = "images/headshots"
        self.headshot_files = []
        self.headshot_index = 0
        self.picker_image = None
        self.picker_label = None
        # Fullscreen glitch effect state
        self.glitch_active = False
        self.glitch_overlay = None
        self.glitch_count = 0
        self.glitch_target = 0
        self.cooldown_count = 0
        self.cooldown_target = 0
        self._fs_label = None
        self._fs_headshot = None
        self._glitch_band_buf = None   # keep ref so GC won't collect it
        self._glitch_img_dsc = None
        ## Small state machine to handle button presses in the app
        self.app_states = [
            "default",
            "enter_add_username",
            "in_add_username",
            "enter_fullscreen",
            "in_fullscreen",
            "enter_pick_font",
            "in_pick_font",
            "enter_pick_image",
            "in_pick_image",
        ]
        self.app_state = 0

    def start(self):
        """Register the app with the system.
        This is where to register any functions to be called when a message of that protocol is received.
        The app will start running in the background.
        If you don't have anything else to add, you can delete this method.
        """
        super().start()
        # register_receiver(NEW_PROTOCOL, self.receive_message)

    def run_foreground(self):
        """Run one pass of the app's behavior when it is in the foreground (has keyboard input and control of the screen).
        You do not need to loop here, and the app will sleep for at least self.foreground_sleep_ms milliseconds between calls.
        Don't block in this function, for it will block reading the radio and keyboard.
        If the app only runs in the background, you can delete this method.
        """

        if self.app_states[self.app_state] == "default":
            print("default mode")
            if self.badge.keyboard.f1():
                self.app_state = self.app_states.index("enter_add_username")
            if self.badge.keyboard.f2():
                self.app_state = self.app_states.index("enter_pick_image")
            if self.badge.keyboard.f3():
                self.app_state = self.app_states.index("enter_fullscreen")
            if self.badge.keyboard.f4():
                pass
            if self.badge.keyboard.f5():
                self.badge.display.clear()
                self.switch_to_background()

        if self.app_states[self.app_state] == "enter_add_username":
            print("enter username")
            self.p.create_text_box(self.username)
            self.app_state = self.app_states.index("in_add_username")
            self.p.set_menubar_button_label(4, "Done")

        if self.app_states[self.app_state] == "in_add_username":
            key, text = self.p.text_box_type(self.badge.keyboard)

            if self.badge.keyboard.f5() or self.badge.keyboard.f1():
                self.username = self.p.text_box.get_text().strip()
                self.badge.config.set("nametag", self.username)
                self.badge.config.flush()
                self.p.infobar_left.set_text(f"Hello, My Name Is: {self.username}")
                self.p.close_text_box()
                self.p.set_menubar_button_label(4, "Home")
                self.app_state = self.app_states.index("default")
                # Re-render the main view so the updated name appears immediately
                self.switch_to_foreground()
                return

        if self.app_states[self.app_state] == "enter_fullscreen":
            ## overlay
            print("enter fullscreen")
            ## This screen overlays the previous screen.
            ## If you want a custom background, colors, whatever... this is where you break things.
            self.fullscreen = lvgl.obj(lvgl.screen_active())
            self.fullscreen.add_style(styles.base_style, lvgl.STATE.DEFAULT)
            self.fullscreen.set_width(lvgl.pct(100))
            self.fullscreen.set_height(lvgl.pct(100))

            # Build fullscreen content: image on the left, name on the right (no scaling)
            self._fs_headshot = None
            if self.show_image and self.image_path:
                try:
                    self._fs_headshot = graphics.create_image(self.image_path, self.fullscreen)
                    self._fs_headshot.set_style_radius(40, 0)
                    self._fs_headshot.align(lvgl.ALIGN.LEFT_MID, 10, 0)
                except Exception as e:
                    print("Nametag FS image load failed:", e)
                    self._fs_headshot = None

            self._fs_label = lvgl.label(self.fullscreen)
            self._fs_label.set_style_text_font(self.font, lvgl.STATE.DEFAULT)
            if self._fs_headshot:
                numlines = self.username.count("\n") + 1
                if numlines == 1:
                    self._fs_label.align_to(self._fs_headshot, lvgl.ALIGN.OUT_RIGHT_MID, 10, 0)
                elif numlines == 2:
                    self._fs_label.align_to(self._fs_headshot, lvgl.ALIGN.OUT_RIGHT_MID, 10, -30)
                else:
                    self._fs_label.align_to(self._fs_headshot, lvgl.ALIGN.OUT_RIGHT_TOP, 10, -20)
            else:
                self._fs_label.align(lvgl.ALIGN.CENTER, 0, 0)
            self._fs_label.set_text(self.username)

            # Initialize glitch counters
            self.glitch_active = False
            self.glitch_overlay = None
            self.glitch_count = 0
            self.glitch_target = 0
            self.cooldown_count = 0
            self.cooldown_target = urandom.randint(_GLITCH_COOLDOWN_MIN, _GLITCH_COOLDOWN_MAX)

            self.app_state = self.app_states.index("in_fullscreen")

        if self.app_states[self.app_state] == "in_fullscreen":
            if (
                self.badge.keyboard.f1()
                or self.badge.keyboard.f2()
                or self.badge.keyboard.f3()
                or self.badge.keyboard.f4()
                or self.badge.keyboard.f5()
            ):
                self._stop_glitch()
                self.fullscreen.delete()
                self.app_state = self.app_states.index("default")
            else:
                if not self.glitch_active:
                    self.cooldown_count += 1
                    if self.cooldown_count % 5 == 0:
                        print(f"[glitch] cooldown {self.cooldown_count}/{self.cooldown_target}")
                    if self.cooldown_count >= self.cooldown_target:
                        print("[glitch] cooldown expired -> _start_glitch")
                        self._start_glitch()
                else:
                    self.glitch_count += 1
                    print(f"[glitch] active frame {self.glitch_count}/{self.glitch_target}")
                    if self.glitch_count >= self.glitch_target:
                        print("[glitch] glitch expired -> _stop_glitch")
                        self._stop_glitch()

        ## Scaffolding here for changing fonts on the fly. Check out the git repo for updates.
        ## Amaze your friends and confound your enemies!
        if self.app_states[self.app_state] == "enter_pick_font":
            print("enter pick_font")
            """pull up a scroller menu to pick fonts from"""
            self.app_state = self.app_states.index("in_pick_font")

        if self.app_states[self.app_state] == "in_pick_font":
            """keys up down enter, any fn key"""
            self.app_state = self.app_states.index("default")

        # Enter image picker: list images/headshots/*.png and show preview with filename
        if self.app_states[self.app_state] == "enter_pick_image":
            try:
                files = []
                for fname in os.listdir(self.image_dir):
                    fn_lower = fname.lower()
                    if fn_lower.endswith(".png"):
                        files.append(fname)
                files.sort()
                self.headshot_files = files
            except Exception as e:
                print("Nametag: listdir failed:", e)
                self.headshot_files = []

            if not self.headshot_files:
                # No images found, notify and return
                try:
                    self.p.infobar_left.set_text("No headshots in images/headshots/")
                except Exception as e:
                    print("Nametag: failed to set infobar text:", e)
                self.app_state = self.app_states.index("default")
            else:
                # Start at current selection if present
                try:
                    current_basename = self.image_path.split("/")[-1]
                    if current_basename in self.headshot_files:
                        self.headshot_index = self.headshot_files.index(current_basename)
                    else:
                        self.headshot_index = 0
                except Exception:
                    self.headshot_index = 0

                # Clear current content widgets
                try:
                    if self.headshot:
                        self.headshot.delete()
                        self.headshot = None
                except Exception:
                    # Ignore errors during headshot widget deletion (e.g., already deleted or not initialized)
                    pass
                try:
                    if self.name_label:
                        self.name_label.delete()
                        self.name_label = None
                except Exception:
                    # It is safe to ignore errors when deleting the name label, as it may not exist or may have already been deleted.
                    pass

                # Build picker preview
                try:
                    fullpath = self.image_dir + "/" + self.headshot_files[self.headshot_index]
                    self.picker_image = graphics.create_image(fullpath, self.p.content)
                    self.picker_image.set_style_radius(40, 0)
                    self.picker_image.align(lvgl.ALIGN.LEFT_MID, 10, 0)
                except Exception as e:
                    print("Nametag: picker image load failed:", e)
                    self.picker_image = None

                self.picker_label = lvgl.label(self.p.content)
                label_text = self.headshot_files[self.headshot_index]
                if self.picker_image:
                    self.picker_label.align_to(self.picker_image, lvgl.ALIGN.OUT_RIGHT_MID, 10, 0)
                else:
                    self.picker_label.align(lvgl.ALIGN.CENTER, 0, 0)
                self.picker_label.set_text(label_text)

                # Update menubar for picker controls: F1 Select, F3 Prev, F4 Next, F5 Cancel
                try:
                    self.p.set_menubar_button_label(0, "Select")
                    self.p.set_menubar_button_label(1, "Hide Img")
                    self.p.set_menubar_button_label(2, "Prev")
                    self.p.set_menubar_button_label(3, "Next")
                    self.p.set_menubar_button_label(4, "Cancel")
                except Exception:
                    # Ignore errors when setting menubar button labels; non-critical UI update.
                    pass
                self.app_state = self.app_states.index("in_pick_image")

        # Handle image picker navigation and selection
        if self.app_states[self.app_state] == "in_pick_image":
            # Prev (F3)
            if self.badge.keyboard.f3():
                if self.headshot_files:
                    self.headshot_index = (self.headshot_index - 1) % len(self.headshot_files)
                    # Refresh preview
                    try:
                        if self.picker_image:
                            self.picker_image.delete()
                    except Exception:
                        # Ignore errors when deleting picker image; image may not exist or may already be deleted.
                        pass
                    fullpath = self.image_dir + "/" + self.headshot_files[self.headshot_index]
                    try:
                        self.picker_image = graphics.create_image(fullpath, self.p.content)
                        self.picker_image.set_style_radius(40, 0)
                        self.picker_image.align(lvgl.ALIGN.LEFT_MID, 10, 0)
                    except Exception as e:
                        print("Nametag: picker image load failed:", e)
                        self.picker_image = None
                    try:
                        if self.picker_label:
                            self.picker_label.delete()
                    except Exception:
                        # Ignore errors if label deletion fails (e.g., label already deleted or not present)
                        pass
                    self.picker_label = lvgl.label(self.p.content)
                    if self.picker_image:
                        self.picker_label.align_to(self.picker_image, lvgl.ALIGN.OUT_RIGHT_MID, 10, 0)
                    else:
                        self.picker_label.align(lvgl.ALIGN.CENTER, 0, 0)
                    self.picker_label.set_text(self.headshot_files[self.headshot_index])

            # Next (F4)
            if self.badge.keyboard.f4():
                if self.headshot_files:
                    self.headshot_index = (self.headshot_index + 1) % len(self.headshot_files)
                    # Refresh preview
                    try:
                        if self.picker_image:
                            self.picker_image.delete()
                    except Exception as e:
                        print("Nametag: failed to delete picker_image:", e)
                    fullpath = self.image_dir + "/" + self.headshot_files[self.headshot_index]
                    try:
                        self.picker_image = graphics.create_image(fullpath, self.p.content)
                        self.picker_image.set_style_radius(40, 0)
                        self.picker_image.align(lvgl.ALIGN.LEFT_MID, 10, 0)
                    except Exception as e:
                        print("Nametag: picker image load failed:", e)
                        self.picker_image = None
                    try:
                        if self.picker_label:
                            self.picker_label.delete()
                    except Exception:
                        # Ignore errors when deleting picker_label; it may not exist or may already be deleted.
                        pass
                    self.picker_label = lvgl.label(self.p.content)
                    if self.picker_image:
                        self.picker_label.align_to(self.picker_image, lvgl.ALIGN.OUT_RIGHT_MID, 10, 0)
                    else:
                        self.picker_label.align(lvgl.ALIGN.CENTER, 0, 0)
                    self.picker_label.set_text(self.headshot_files[self.headshot_index])

            # Select (F1)
            if self.badge.keyboard.f1():
                if self.headshot_files:
                    chosen = self.image_dir + "/" + self.headshot_files[self.headshot_index]
                    try:
                        self.badge.config.set("nametag_image", chosen.encode())
                        self.badge.config.set("nametag_show_image", b"true")
                        self.badge.config.flush()
                    except Exception as e:
                        print("Nametag: failed to save config:", e)
                    # Small confirmation
                    try:
                        self.p.infobar_left.set_text("Headshot set: " + self.headshot_files[self.headshot_index])
                    except Exception:
                        # Ignore errors setting confirmation message to avoid interrupting user flow
                        pass
                # Exit picker and rebuild main view
                try:
                    if self.picker_image:
                        self.picker_image.delete()
                        self.picker_image = None
                    if self.picker_label:
                        self.picker_label.delete()
                        self.picker_label = None
                except Exception:
                    # Ignore errors during cleanup; picker image/label may already be deleted or None.
                    pass
                # Re-render the whole screen to reflect change
                self.app_state = self.app_states.index("default")
                self.switch_to_foreground()
                return

            # Hide Img (F2)
            if self.badge.keyboard.f2():
                try:
                    self.badge.config.set("nametag_show_image", b"false")
                    self.badge.config.flush()
                except Exception as e:
                    print("Nametag: failed to save config:", e)
                # Exit picker and rebuild main view
                try:
                    if self.picker_image:
                        self.picker_image.delete()
                        self.picker_image = None
                    if self.picker_label:
                        self.picker_label.delete()
                        self.picker_label = None
                except Exception:
                    # Ignore errors during cleanup; picker image/label may already be deleted or None.
                    pass
                # Re-render the whole screen to reflect change
                self.app_state = self.app_states.index("default")
                self.switch_to_foreground()
                return

            # Cancel/Back (F5)
            if self.badge.keyboard.f5():
                try:
                    if self.picker_image:
                        self.picker_image.delete()
                        self.picker_image = None
                    if self.picker_label:
                        self.picker_label.delete()
                        self.picker_label = None
                except Exception:
                    # It is safe to ignore errors here, as the UI elements may already be deleted or not exist.
                    pass
                # Restore default labels
                try:
                    self.p.set_menubar_button_label(0, "Name")
                    self.p.set_menubar_button_label(1, "Pick Img")
                    self.p.set_menubar_button_label(2, "Fullscreen")
                    self.p.set_menubar_button_label(3, "")
                    self.p.set_menubar_button_label(4, "Home")
                except Exception:
                    pass
                self.app_state = self.app_states.index("default")
                # Rebuild main content
                self.switch_to_foreground()
                return

    def _start_glitch(self):
        """Snapshot the fullscreen pixels, shift a random band of rows right in the buffer, overlay as image."""
        SCREEN_W = _GLITCH_SCREEN_W
        SCREEN_H = _GLITCH_SCREEN_H
        SHIFT_PX = _GLITCH_SHIFT_PX
        ROW_BYTES = SCREEN_W * 2  # RGB565: 2 bytes per pixel

        band_h = urandom.randint(_GLITCH_BAND_H_MIN, _GLITCH_BAND_H_MAX)
        band_y = urandom.randint(0, max(1, SCREEN_H - band_h))
        print(f"[glitch] _start_glitch band_y={band_y} band_h={band_h}")

        # --- Step 1: probe snapshot API availability ---
        has_snapshot = hasattr(lvgl, "snapshot_take")
        has_snapshot_obj = hasattr(lvgl, "snapshot")
        print(f"[glitch] lvgl.snapshot_take={has_snapshot} lvgl.snapshot={has_snapshot_obj}")

        snap = None
        if has_snapshot:
            try:
                snap = lvgl.snapshot_take(self.fullscreen, lvgl.COLOR_FORMAT.RGB565)
                print(f"[glitch] snapshot_take result: {snap}, type={type(snap)}")
                if snap is not None:
                    print(f"[glitch] snap attrs: data={getattr(snap,'data','N/A')} data_size={getattr(snap,'data_size','N/A')}")
            except Exception as e:
                print(f"[glitch] snapshot_take exception: {e}")
                snap = None
        elif has_snapshot_obj:
            try:
                snap = lvgl.snapshot.take(self.fullscreen, lvgl.COLOR_FORMAT.RGB565)
                print(f"[glitch] snapshot.take result: {snap}")
            except Exception as e:
                print(f"[glitch] snapshot.take exception: {e}")
                snap = None

        if snap is None:
            print("[glitch] snapshot unavailable - aborting glitch this cycle")
            self.glitch_active = True
            self.glitch_count = 0
            self.glitch_target = 1
            return

        # --- Step 2: get the raw bytes from C_Array ---
        # snap.data is a C uint8_t* pointer. memoryview() gives 4 bytes (the pointer address).
        # We must read those 4 bytes as a little-endian uint32 then dereference with uctypes.
        raw = None
        try:
            data_val = snap.data
            data_size = snap.data_size
            print(f"[glitch] data type={type(data_val)} size={data_size}")
            if isinstance(data_val, int):
                raw = uctypes.bytearray_at(data_val, data_size)
                print(f"[glitch] uctypes(int) OK len={len(raw)}")
            elif isinstance(data_val, (bytes, bytearray, memoryview)):
                raw = data_val
                print(f"[glitch] bytes-like len={len(raw)}")
            else:
                # C_Array: memoryview gives the 4-byte pointer value, not the data
                mv = memoryview(data_val)
                if len(mv) == 4:
                    ptr_addr = mv[0] | (mv[1] << 8) | (mv[2] << 16) | (mv[3] << 24)
                    print(f"[glitch] deref ptr 0x{ptr_addr:08x}")
                    raw = uctypes.bytearray_at(ptr_addr, data_size)
                    print(f"[glitch] uctypes deref OK len={len(raw)}")
                else:
                    # Full data in memoryview directly
                    raw = mv
                    print(f"[glitch] memoryview direct len={len(raw)}")
        except Exception as e:
            print(f"[glitch] buffer access exception: {e}")

        if raw is None or len(raw) < (band_y + band_h) * ROW_BYTES:
            print(f"[glitch] raw buffer too small or None: {len(raw) if raw else 'None'}, need {(band_y+band_h)*ROW_BYTES}")
            snap = None  # allow GC
            self.glitch_active = True
            self.glitch_count = 0
            self.glitch_target = 1
            return

        # --- Step 3: build glitched band buffer ---
        SHIFT_BYTES = SHIFT_PX * 2
        band_buf = bytearray(band_h * ROW_BYTES)  # zeroed = black fill on left
        copy_len = ROW_BYTES - SHIFT_BYTES
        for row in range(band_h):
            src_off = (band_y + row) * ROW_BYTES
            dst_off = row * ROW_BYTES
            band_buf[dst_off + SHIFT_BYTES : dst_off + ROW_BYTES] = raw[src_off : src_off + copy_len]
        print(f"[glitch] band_buf built len={len(band_buf)}")

        # Release snapshot — no official free API in this build; drop reference for GC
        raw = None
        snap = None

        # --- Step 4: probe image_dsc_t header format ---
        # Try nested header first (LVGL 9), fall back to flat (older bindings)
        try:
            magic = lvgl.IMAGE_HEADER_MAGIC
        except AttributeError:
            magic = 0x19
        print(f"[glitch] magic=0x{magic:02x}")

        self._glitch_band_buf = band_buf

        # Try nested header format
        img_dsc = None
        try:
            img_dsc = lvgl.image_dsc_t({
                "header": {
                    "magic": magic,
                    "cf": int(lvgl.COLOR_FORMAT.RGB565),
                    "flags": 0,
                    "w": SCREEN_W,
                    "h": band_h,
                    "stride": ROW_BYTES,
                },
                "data_size": len(band_buf),
                "data": band_buf,
            })
            print(f"[glitch] image_dsc_t (nested header) OK: {img_dsc}")
        except Exception as e:
            print(f"[glitch] image_dsc_t nested header failed: {e}")
            img_dsc = None

        if img_dsc is None:
            # Try flat format (may work for some binding versions)
            try:
                img_dsc = lvgl.image_dsc_t({
                    "data_size": len(band_buf),
                    "data": band_buf,
                })
                print(f"[glitch] image_dsc_t (flat) OK: {img_dsc}")
            except Exception as e:
                print(f"[glitch] image_dsc_t flat failed: {e}")
                img_dsc = None

        self._glitch_img_dsc = img_dsc
        if img_dsc is None:
            print("[glitch] could not create image_dsc_t at all")
            self._glitch_band_buf = None
            self.glitch_active = True
            self.glitch_count = 0
            self.glitch_target = 1
            return

        # --- Step 5: create overlay image widget ---
        try:
            self.glitch_overlay = lvgl.image(self.fullscreen)
            print(f"[glitch] lvgl.image widget created: {self.glitch_overlay}")
            self.glitch_overlay.set_src(img_dsc)
            print("[glitch] set_src OK")
            self.glitch_overlay.set_pos(0, band_y)
            print(f"[glitch] set_pos(0, {band_y}) OK")
        except Exception as e:
            print(f"[glitch] overlay widget exception: {e}")
            self.glitch_overlay = None
            self._glitch_band_buf = None
            self._glitch_img_dsc = None

        self.glitch_active = True
        self.glitch_count = 0
        self.glitch_target = urandom.randint(_GLITCH_FRAMES_MIN, _GLITCH_FRAMES_MAX)
        print(f"[glitch] done. overlay={self.glitch_overlay} target_frames={self.glitch_target}")

    def _stop_glitch(self):
        """Remove the glitch overlay, release buffer refs, arm next cooldown."""
        if self.glitch_overlay is not None:
            try:
                self.glitch_overlay.delete()
            except Exception:
                pass
            self.glitch_overlay = None
        self._glitch_img_dsc = None
        self._glitch_band_buf = None  # safe to GC now that the widget is deleted
        self.glitch_active = False
        self.cooldown_count = 0
        self.cooldown_target = urandom.randint(_GLITCH_COOLDOWN_MIN, _GLITCH_COOLDOWN_MAX)

    def run_background(self):
        """App behavior when running in the background.
        You do not need to loop here, and the app will sleep for at least self.background_sleep_ms milliseconds between calls.
        Don't block in this function, for it will block reading the radio and keyboard.
        If the app only does things when running in the foreground, you can delete this method.
        """
        super().run_background()

    def switch_to_foreground(self):
        """Set the app as the active foreground app.
        This will be called by the Menu when the app is selected.
        Any one-time logic to run when the app comes to the foreground (such as setting up the screen) should go here.
        If you don't have special transition logic, you can delete this method.
        """
        super().switch_to_foreground()
        self.p = Page()
        ## Note this order is important: it renders top to bottom that the "content" section expands to fill empty space
        ## If you want to go fully clean-slate, you can draw straight onto the p.scr object, which should fit the full screen.
        self.username = self.badge.config.get("nametag").decode().strip()
        # Refresh image config on entry
        try:
            self.show_image = self.badge.config.get("nametag_show_image").decode().strip() in ("1", "true", "True")
        except Exception:
            self.show_image = False
        try:
            self.image_path = self.badge.config.get("nametag_image").decode().strip()
        except Exception:
            self.image_path = "images/headshots/wrencher.png"
        self.p.create_infobar([f"Hello, My Name Is: {self.username}", "Nametag App"])
        self.p.create_content()
        self.p.create_menubar(["Name", "Pick Img", "Fullscreen", "", "Home"])
        # Build content: image on the left (rounded), name label to the right. No scaling.
        self.name_label = None
        self.headshot = None
        try:
            if self.show_image and self.image_path:
                self.headshot = graphics.create_image(self.image_path, self.p.content)
                self.headshot.set_style_radius(40, 0)
                self.headshot.align(lvgl.ALIGN.LEFT_MID, 10, 0)
        except Exception as e:
            # If image cannot be loaded, fall back to text-only
            print("Nametag image load failed:", e)
            self.headshot = None
        # Create the name label
        self.name_label = lvgl.label(self.p.content)
        self.name_label.set_style_text_font(self.font, lvgl.STATE.DEFAULT)
        if self.headshot:
            # figure out if the label is more than one line
            numlines = self.username.count("\n") + 1
            if numlines == 1:
                self.name_label.align_to(self.headshot, lvgl.ALIGN.OUT_RIGHT_MID, 10, 0)
            elif numlines == 2:
                self.name_label.align_to(self.headshot, lvgl.ALIGN.OUT_RIGHT_MID, 10, -30)
            else:
                self.name_label.align_to(self.headshot, lvgl.ALIGN.OUT_RIGHT_TOP, 10, -20)
        else:
            # Center text if no image
            self.name_label.align(lvgl.ALIGN.CENTER, 0, 0)
        self.name_label.set_text(self.username)
        self.p.replace_screen()

    def switch_to_background(self):
        """Set the app as a background app.
        This will be called when the app is first started in the background and when it stops being in the foreground.
        If you don't have special transition logic, you can delete this method.
        """
        self.p = None  ## remove the screen
        super().switch_to_background()
