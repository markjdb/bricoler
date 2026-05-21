import os
from pathlib import Path

import pytest

from bricoler import util


requires_freebsd = pytest.mark.skipif(os.uname().sysname.lower() != "freebsd", reason="Test must be run on FreeBSD")


def test_chdir(tmpdir):
    """Test .util.chdir(..) context manager."""
    tmpdir_p = Path(tmpdir)
    assert Path.cwd() != tmpdir_p
    with util.chdir(tmpdir_p):
        assert Path.cwd() == tmpdir_p
    assert Path.cwd() != tmpdir_p


def test_colour():
    """Test .util.colour(..)."""
    colour = util.ANSIColour.RED
    text = "my fancy message"
    retval = util.colour(text, colour)
    assert retval == f"\033[{colour.value}m{text}\033[0m"


@requires_freebsd
def test_host_machine():
    """Test .util.host_machine()."""

    util.host_machine()
