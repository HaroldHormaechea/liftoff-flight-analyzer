"""fpv-review: measured debriefs from saved FPV sim replays.

Two subtrees, and one rule that is the whole architecture:

    common/          may import common/ and the standard library, nothing else
    sources/<sim>/   may import common/ and its own siblings, never another sim

cli.py is the only module allowed to import both, and it does the wiring.
"""
