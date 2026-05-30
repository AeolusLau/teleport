"""Single source of truth for the canary dmg window geometry & colors.

Both scripts/gen_dmg_background.py (paints the static background art) and
scripts/dmg_settings.py (places the Finder icons) must agree on these numbers,
or the app icon / Applications folder won't line up with the painted card and
arrow. scripts/tests/test_dmg_layout.py and test_dmg_settings.py guard that.

Pure data + tiny helpers, no third-party deps, so it imports cleanly under
`uv run pytest` (Pillow is not a test dependency).
"""

# Window content size (== background image size). These exactly match Chrome's
# default install window, read from its mounted dmg: .DS_Store fwi0/fwvh give a
# 480x540 content rect, and the background.png is 480x540.
W = 480
H = 556  # Chrome is 540; a touch more bottom breathing room below the card

# Finder draws every icon at one size. Chrome's .DS_Store icvo encodes 128.
ICON_SIZE = 128
TEXT_SIZE = 12  # Chrome's .DS_Store icvt

# Icon centers (logical px; origin = top-left of the background image). Exactly
# Chrome's Iloc values: app icon on the white upper area, Applications on the card.
APP_CENTER = (240, 122)
APPS_CENTER = (240, 387)

# Lower rounded card (x0, y0, x1, y1) and corner radius. Measured from Chrome's
# background pixels: the solid top edge is at y=287, bottom at 484 (~300x197).
CARD = (90, 287, 389, 484)
CARD_RADIUS = 3  # Chrome's card is near-square: its corner arc spans only ~2px

# Colors. Slate-blue card is a Teleport brand nudge from Chrome's lavender
# (Chrome's measured fill is ~(220,228,250)); we keep our slightly cooler slate.
BG_FILL = (255, 255, 255)
CARD_FILL = (214, 222, 238)
ARROW_FILL = (255, 255, 255)

# The Applications symlink is named with a single space so Finder shows no label
# under it. Chrome's dmg does exactly this (its symlink is also named " ").
APPS_LABEL = " "

# Big white down-arrow, centered on APPS_CENTER x. Matches Chrome's exact arrow
# profile measured from its background: shaft x-width 23 from y=287 (flush with
# the card's top edge) to 307, then a 25px-tall head widening to 51 at y=307 and
# tapering to the tip at y=332.
ARROW_SHAFT_TOP = 287
ARROW_SHAFT_BOTTOM = 307
ARROW_TIP = 332
ARROW_SHAFT_HALFWIDTH = 11
ARROW_HEAD_TOP = 307
ARROW_HEAD_HALFWIDTH = 25


def arrow_shaft():
    """Rectangle (x0, y0, x1, y1) for the arrow shaft."""
    cx = APPS_CENTER[0]
    return (cx - ARROW_SHAFT_HALFWIDTH, ARROW_SHAFT_TOP,
            cx + ARROW_SHAFT_HALFWIDTH, ARROW_SHAFT_BOTTOM)


def arrow_head():
    """Triangle [(x, y), ...] for the arrow head; tip is the last point."""
    cx = APPS_CENTER[0]
    return [(cx - ARROW_HEAD_HALFWIDTH, ARROW_HEAD_TOP),
            (cx + ARROW_HEAD_HALFWIDTH, ARROW_HEAD_TOP),
            (cx, ARROW_TIP)]
