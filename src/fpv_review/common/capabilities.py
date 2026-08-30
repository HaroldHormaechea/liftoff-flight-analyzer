#!/usr/bin/env python3
"""
capabilities.py - what a sim can and cannot tell us, declared rather than found out.

The rule this exists to serve: a stage that receives a declared gap NAMES it and
never infers the value. It is the same rule the project already applies to
missing collision geometry - a recording without a cached scene still draws the
path, the attitude and the impacts, and prints what it could not draw - written
here so that it can cover every field instead of only that one.

The mechanism has two halves, and one of them runs. Each sim's `declare()`
builds the declaration, and cli.py publishes it through `as_json()` as one
additive key in analysis.json. That half is exercised on every report.

The consuming half - `gap()` and `has()` - is provided and has no call site
today. `gap(caps, field)` returns the sentence a report would print AND records
the consultation, so that a stage cannot explain a hole to the reader without
the same call putting it in analysis.json; a second, parallel mechanism for the
same thing is how the two drift apart. Nothing calls it because Liftoff gives it
nothing to do: Liftoff declares no gap that suppresses a finding the report
makes, so `gaps_named_in_this_run` is empty in every report this repository has
produced. It waits here for the sim that does have such a gap. Read it as
provided, not as a rule being enforced today, and not as unfinished work.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

# The three states a field can be in. `DERIVED` is the interesting one: it means
# the number exists and is honest, but it was computed here rather than measured
# by the sim, so a reader should not treat it as ground truth.
AVAILABLE = "available"
DERIVED = "derived"
UNAVAILABLE = "unavailable"


@dataclass
class Capability:
    """One field's status, and why."""
    state: str                       # AVAILABLE | DERIVED | UNAVAILABLE
    note: Optional[str] = None       # how it is obtained, or why it is missing
    conditional_on: Optional[str] = None   # a cache or setup step it depends on


@dataclass
class Capabilities:
    """A sim's whole declaration, plus the record of what was consulted."""
    sim: str
    fields: Dict[str, Capability] = field(default_factory=dict)
    consulted: List[str] = field(default_factory=list)

    def state(self, name):
        cap = self.fields.get(name)
        return cap.state if cap else UNAVAILABLE

    def has(self, name):
        return self.state(name) in (AVAILABLE, DERIVED)

    def as_json(self):
        """The `capabilities` block written into analysis.json.

        Additive and pre-declared: one new top-level key, and for Liftoff no
        change to report.md or report.html at all, because Liftoff declares no
        gap that suppresses a finding the report currently makes."""
        return {
            "sim": self.sim,
            "fields": {k: {"state": c.state,
                           **({"note": c.note} if c.note else {}),
                           **({"conditional_on": c.conditional_on}
                              if c.conditional_on else {})}
                       for k, c in sorted(self.fields.items())},
            "gaps_named_in_this_run": sorted(set(self.consulted)),
        }


def gap(caps, name):
    """The sentence for a field this sim cannot supply, or None if it can.

    Calling this is how a stage declines to infer. It returns the line to print
    and records the consultation, so the same call both explains the hole to the
    reader and puts it in analysis.json."""
    cap = caps.fields.get(name)
    if cap is not None and cap.state in (AVAILABLE, DERIVED):
        return None
    caps.consulted.append(name)
    why = cap.note if cap and cap.note else "not recorded by this sim"
    return "not available from %s: %s (%s)" % (caps.sim, name, why)
