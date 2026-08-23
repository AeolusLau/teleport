"""Shared pytest fixtures/markers for the overlay tooling tests."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


def _probe_symlink_support() -> bool:
    """Can this process create a directory symlink?

    Always true on POSIX. On Windows it needs SeCreateSymbolicLinkPrivilege,
    which an ordinary process only holds when Developer Mode is on -- so this is
    a property of the machine, not of the code under test. Probed once rather
    than inferred from the platform, because the answer differs between two
    Windows boxes running the identical checkout.
    """
    with tempfile.TemporaryDirectory() as d:
        target = Path(d) / "target"
        target.mkdir()
        try:
            os.symlink(target, Path(d) / "link", target_is_directory=True)
            return True
        except OSError:
            return False


CAN_SYMLINK = _probe_symlink_support()

# Applied to tests that must create a REAL symlink (as opposed to a Windows
# junction). Note this is deliberately NOT a way of saying "skip on Windows":
# with Developer Mode on -- which bootstrap.py requires for exactly the same
# reason -- these tests run and must pass on Windows too.
requires_symlinks = pytest.mark.skipif(
    not CAN_SYMLINK,
    reason="creating a symlink needs SeCreateSymbolicLinkPrivilege; turn on "
           "Developer Mode (Settings -> System -> For developers). "
           "bootstrap.py requires the same privilege for the overlay injection "
           "link, because siso will not traverse a junction.",
)
