import dmg_layout as L


def test_portrait_canvas():
    assert L.W > 0 and L.H > 0
    assert L.H > L.W  # portrait window, like Chrome's dmg


def test_card_within_canvas_and_in_lower_region():
    x0, y0, x1, y1 = L.CARD
    assert 0 <= x0 < x1 <= L.W
    assert 0 <= y0 < y1 <= L.H
    assert (y0 + y1) / 2 > L.H / 2  # card sits in the lower half


def test_app_icon_clears_the_card():
    _, card_top, _, _ = L.CARD
    app_bottom = L.APP_CENTER[1] + L.ICON_SIZE / 2
    assert app_bottom < card_top  # app icon on the white area, above the card


def test_apps_folder_inside_card():
    x0, y0, x1, y1 = L.CARD
    cx, cy = L.APPS_CENTER
    half = L.ICON_SIZE / 2
    assert x0 <= cx - half and cx + half <= x1
    assert y0 <= cy - half and cy + half <= y1


def test_arrow_sits_above_folder_inside_card():
    # The tip points down toward the folder (above its center, like Chrome's,
    # which slightly overlaps the folder cell's top padding).
    assert L.ARROW_TIP < L.APPS_CENTER[1]
    # Arrow shaft is flush with the card's top edge (Chrome: both at y=287),
    # not floating mid-card.
    assert L.CARD[1] <= L.ARROW_SHAFT_TOP <= L.CARD[1] + 4


def test_apps_label_is_blank():
    assert L.APPS_LABEL.strip() == ""          # blank name => no Finder label


def test_arrow_helpers_match_constants():
    sx0, sy0, sx1, sy1 = L.arrow_shaft()
    assert (sy0, sy1) == (L.ARROW_SHAFT_TOP, L.ARROW_SHAFT_BOTTOM)
    head = L.arrow_head()
    assert head[-1] == (L.APPS_CENTER[0], L.ARROW_TIP)  # tip is last point
