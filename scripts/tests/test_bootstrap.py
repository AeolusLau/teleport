import bootstrap


def test_gclient_template_enables_pgo_profiles():
    assert '"checkout_pgo_profiles": True' in bootstrap.GCLIENT_SOLUTION


def test_ensure_gclient_writes_when_missing(tmp_path):
    p = tmp_path / ".gclient"
    bootstrap.ensure_gclient(p)
    assert p.exists()
    assert "checkout_pgo_profiles" in p.read_text()


def test_ensure_gclient_rewrites_legacy_file_without_var(tmp_path):
    p = tmp_path / ".gclient"
    p.write_text(
        'solutions = [\n'
        '  {\n'
        '    "name": "src",\n'
        '    "url": "https://chromium.googlesource.com/chromium/src.git",\n'
        '    "managed": False,\n'
        '    "custom_deps": {},\n'
        '    "custom_vars": {},\n'
        '  },\n'
        ']\n'
    )
    bootstrap.ensure_gclient(p)
    assert "checkout_pgo_profiles" in p.read_text()


def test_ensure_gclient_is_noop_when_var_present(tmp_path):
    p = tmp_path / ".gclient"
    bootstrap.ensure_gclient(p)
    sentinel = p.read_text() + "# user edit\n"
    p.write_text(sentinel)
    bootstrap.ensure_gclient(p)  # var already present -> must not clobber
    assert p.read_text() == sentinel
