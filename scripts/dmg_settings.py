"""dmgbuild settings for the Teleport dogfood disk image.

Invoked by scripts/package_release.py via:
  dmgbuild -s scripts/dmg_settings.py \
    -D app=<signed Teleport.app> -D icon=<volume .icns> -D background=<tiff> \
    Teleport <out.dmg>

dmgbuild evaluates this file with `defines` (the -D values) in scope. Icon
positions match the drawn background (brand/dmg/background.png): Teleport.app on
the left, the Applications symlink on the right.
"""
import os.path

app = defines.get("app")  # noqa: F821 (dmgbuild injects `defines`)
appname = os.path.basename(app)

# Contents of the image: the app plus a named Applications symlink.
files = [app]
symlinks = {"Applications": "/Applications"}

# Volume icon (the app's .icns), and the window background art.
icon = defines.get("icon")  # noqa: F821
background = defines.get("background")  # noqa: F821

# lzma-compressed UDIF (needs macOS 10.15+; our floor is 12.0). Much smaller
# than zlib UDZO — matches the compactness of Chrome's ULMO pkg-dmg output.
format = "ULMO"

# Icon-view layout. window_rect is ((x, y), (width, height)); the background
# image is 640x400 to match.
default_view = "icon-view"
window_rect = ((220, 220), (640, 400))
icon_size = 128
text_size = 13
icon_locations = {
    appname: (160, 196),
    "Applications": (480, 196),
}
