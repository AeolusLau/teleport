import pytest

import check_upstream_release as cur


def test_version_key_orders_numerically():
    assert cur.version_key("151.0.7922.9") < cur.version_key("151.0.7922.76")
    assert cur.version_key("150.0.7871.213") < cur.version_key("151.0.7922.34")


def test_classify_current_when_pin_is_latest():
    v = cur.classify("151.0.7922.76", {"mac": ["151.0.7922.76", "151.0.7922.75"],
                                       "win64": ["151.0.7922.76"]})
    assert v.status == "current"
    assert v.platforms_disagree is False


def test_classify_patch_available_same_branch():
    v = cur.classify("151.0.7922.76", {"mac": ["151.0.7922.132", "151.0.7922.76"],
                                       "win64": ["151.0.7922.132"]})
    assert v.status == "patch_available"
    assert v.latest == "151.0.7922.132"


def test_classify_milestone_moved_on_new_build():
    v = cur.classify("151.0.7922.76", {"mac": ["152.0.8001.40"],
                                       "win64": ["152.0.8001.40"]})
    assert v.status == "milestone_moved"
    assert v.latest == "152.0.8001.40"


def test_classify_flags_desktop_platform_disagreement():
    v = cur.classify("151.0.7922.76", {"mac": ["151.0.7922.90"],
                                       "win64": ["151.0.7922.76"]})
    assert v.platforms_disagree is True


def test_classify_ignores_linux_for_the_verdict():
    """Linux ships a subset of the desktop sequence; it must not make us think
    we are ahead or behind."""
    v = cur.classify("151.0.7922.76", {"mac": ["151.0.7922.76"],
                                       "win64": ["151.0.7922.76"],
                                       "linux": ["151.0.7922.75"]})
    assert v.status == "current"
    assert v.platforms_disagree is False


def test_classify_rejects_empty_desktop_data():
    with pytest.raises(ValueError):
        cur.classify("151.0.7922.76", {"linux": ["151.0.7922.75"]})


def test_classify_flags_missing_platform_when_mac_empty():
    """mac reported no data (transient fetch failure, empty payload, ...)
    while win64 reported normally. The verdict must say so distinctly from
    platforms_disagree, since only one platform's data was actually checked."""
    v = cur.classify("151.0.7922.76", {"mac": [], "win64": ["151.0.7922.76"]})
    assert v.status == "current"
    assert v.platforms_disagree is False
    assert v.missing_platforms == ("mac",)


def test_classify_flags_missing_platform_when_win64_empty():
    v = cur.classify("151.0.7922.76", {"mac": ["151.0.7922.76"], "win64": []})
    assert v.status == "current"
    assert v.platforms_disagree is False
    assert v.missing_platforms == ("win64",)


def test_classify_missing_platforms_empty_when_both_report():
    v = cur.classify("151.0.7922.76", {"mac": ["151.0.7922.76"],
                                       "win64": ["151.0.7922.76"]})
    assert v.missing_platforms == ()
