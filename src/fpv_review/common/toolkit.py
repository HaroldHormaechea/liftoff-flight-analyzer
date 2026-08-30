#!/usr/bin/env python3
"""
toolkit.py - where the toolkit ends and the user's own project begins.

Extracted from liftoff_replay.py, which owned this guard only because it was the
leaf module everything else already imported. Nothing here is Liftoff-specific:
it is a data-placement boundary, so it belongs in common/.

The rule it enforces: pilot profiles, replays, reports and PB history are the
user's data and must live in the user's project, never inside a toolkit that may
be shared or public. `.gitignore` already covers those paths, but an ignore rule
is one `git add -f` away from being wrong, and it does nothing about the data
physically sitting in a public checkout.
"""

import os
import sys
from pathlib import Path


def mounted_via_link():
    """True when this toolkit is being run through a symlink or junction.

    Someone who clones the repo and works inside it is running the real path,
    and writing their replays and reports there is exactly right. Someone who
    has mounted the toolkit into another project - as a skill, say - is running
    a linked path, and for them the toolkit directory is shared code that their
    own flight data must never leak into.

    Comparing the invoked path with the resolved one distinguishes the two
    without any configuration to forget."""
    here = os.path.abspath(__file__)
    return os.path.normcase(here) != os.path.normcase(os.path.realpath(here))


def toolkit_root():
    """The repository root, found by searching upward for two marker files.

    This used to be `Path(realpath(__file__)).parent.parent` in
    liftoff_replay.py, which was correct only because that file sat exactly one
    level below the root. Under src/fpv_review/common/ the depth is different,
    and the failure mode of a wrong count is the worst kind: TOOLKIT_ROOT points
    at some inner directory, no write ever lands underneath it, and
    refuse_inside_toolkit() silently stops guarding anything. A search has no
    depth to get wrong, so a later move cannot quietly disarm the guard.

    Two markers, not one, because a user's own project may perfectly well
    contain a pyproject.toml; only this toolkit has SKILL.md beside one.

    Raises rather than guessing if neither is found: a toolkit that cannot
    locate itself must fail loudly, not fall back to a root that disables the
    check."""
    for d in Path(os.path.realpath(__file__)).parents:
        if (d / "SKILL.md").is_file() and (d / "pyproject.toml").is_file():
            return d
    raise RuntimeError(
        "cannot locate the toolkit root: no ancestor of %s contains both "
        "SKILL.md and pyproject.toml. The toolkit looks incomplete - a partial "
        "copy of src/ is not enough, the whole repository is needed."
        % os.path.realpath(__file__))


TOOLKIT_ROOT = toolkit_root()


def refuse_inside_toolkit(target, what):
    """Hard stop before writing personal data into shared code.

    Only fires when the toolkit is mounted via a link, so it cannot get in the
    way of the ordinary clone-and-run case. `.gitignore` already covers these
    paths, but an ignore rule is one `git add -f` away from being wrong, and it
    does nothing about the data physically sitting in a public checkout."""
    if not mounted_via_link():
        return
    t = Path(os.path.realpath(str(target)))
    if t == TOOLKIT_ROOT or TOOLKIT_ROOT in t.parents:
        sys.exit(
            "refusing to write %s inside the toolkit.\n"
            "  toolkit: %s\n"
            "  target:  %s\n"
            "This toolkit is mounted through a link, so it is shared code and may "
            "be public. Pass a path in your own project instead." % (what, TOOLKIT_ROOT, t))
