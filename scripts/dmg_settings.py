"""dmgbuild settings for the Teleport dogfood disk image.

Invoked by scripts/package.py via:
  dmgbuild -s scripts/dmg_settings.py \
    -D app=<signed Teleport.app> -D icon=<volume .icns> -D background=<tiff> \
    Teleport <out.dmg>

dmgbuild evaluates this file with `defines` (the -D values) in scope.

Portrait layout mirroring Chrome's default install window: the app icon on the
white upper area, a lower rounded card with a big white down-arrow above the
Applications folder. Geometry MUST stay in sync with scripts/dmg_layout.py
(which paints the matching background art); scripts/tests/test_dmg_settings.py
guards the alignment.
"""
import os.path

app = defines.get("app")  # noqa: F821 (dmgbuild injects `defines`)
appname = os.path.basename(app)

# Contents: the app plus an Applications symlink named with a single space, so
# Finder shows no label under it (matches Chrome's default install window).
files = [app]
symlinks = {" ": "/Applications"}

# Volume icon (the app's .icns) and the window background art.
icon = defines.get("icon")  # noqa: F821
background = defines.get("background")  # noqa: F821

# lzma-compressed UDIF (needs macOS 10.15+; our floor is 12.0).
format = "ULMO"

# Portrait icon-view layout. window_rect is ((x, y), (width, height)); width and
# height equal the background image size (dmg_layout.W, dmg_layout.H = 480, 556).
# Position mirrors Chrome's window (its .DS_Store fwi0 origin is (240, 180)).
default_view = "icon-view"
window_rect = ((240, 180), (480, 556))
icon_size = 128
text_size = 12
icon_locations = {
    appname: (240, 122),   # dmg_layout.APP_CENTER  — app icon on the white area
    " ": (240, 387),       # dmg_layout.APPS_CENTER — Applications folder on card
}
