# Use Case 02: Write the contributor guide, and fix what writing it exposed

> **Scope widened by the author, 2026-08-30, after the analyst's first pass.**
> This use case was documentation-only. Writing the guide exposed two code
> defects and two places where ADR-0001 promises more than the code delivers, so
> the fixes are now **in scope and land in the same run** — a guide that documents
> a contract the code does not honour would be false on the day it shipped.
> Criterion 13 is replaced accordingly, and criteria 14–19 are added.

## Summary

Replace the placeholder `CONTRIBUTING.md` — currently the single line "To be
defined. I'm pending a rearchitecture to simplify contribution and adding new
sims here." — with a real contributor guide, now that the rearchitecture it was
waiting for has merged (PR #1, ADR-0001). The guide documents the two extension
points the new layout creates: **adding a sim parser**, meaning a new
`sources/<sim>/` that implements the per-sim contract — the required module
surface, the dataclasses it must emit, and the capabilities declaration for what
that sim cannot provide — and **adding a measurement**, meaning a new derived
quantity in `common/analysis.py` alongside the existing tilt, sideslip and turn
radius, including the decision of whether its constants are sim calibration
belonging in `sources/<sim>/calibration.py` or presentation belonging in
`common/`. It also states how a change is verified in a project that has
deliberately no test suite, and the two constraints a newcomer would otherwise
breach: the analysis path takes no third-party dependency, and no game asset,
replay or pilot profile is ever committed. A short section names the
`project-builder` harness as how this project is built and evolved, so a reader
understands why `use-cases/` and `use-cases/plans/` exist. The guide is written
to ASD-STE100's rules — short sentences, active voice, one instruction per
sentence, one meaning per term — without claiming certified compliance, because
the approved vocabulary is published only in the licensed specification.

## Acceptance Criteria

1. `CONTRIBUTING.md` no longer contains the placeholder sentence, and no longer
   describes the rearchitecture as pending.
2. The guide documents **adding a sim parser** with a concrete path through real
   files: which modules a new `sources/<sim>/` must provide, what each returns,
   and which are optional. It cites ADR-0001 § "The per-sim contract" rather
   than restating it, so the two cannot drift apart.
3. The guide names the dataclasses a sim must emit — `FlightSample`,
   `FlightSeries`, `SessionMeta`, `LapSet` — and states where their definitions
   live, with their units and coordinate frame referenced, not copied.
4. The guide explains the **capabilities declaration**: how a sim states what it
   cannot provide, and the rule that a stage receiving a declared gap names it in
   the report and never infers the value.
5. The guide documents **adding a measurement**: where a new derived quantity is
   computed, how it reaches the report, and the rule for its constants —
   *physical constants are calibration, presentational ones are not* — with the
   existing split as the worked example.
6. The guide states the **three-layer import rule** (`common/` imports only
   `common/` and the standard library; `sources/<sim>/` imports `common/` and its
   own siblings, never another sim; `cli.py` alone may import both) and says how a
   contributor checks their change against it.
7. The guide explains **how a change is verified here**: run the real pipeline
   against a saved replay and compare what it produces, because the project has no
   test suite by decision. It states plainly that "the tests pass" is not a claim
   available in this repository.
8. The guide states both hard constraints: **no third-party dependency on the
   analysis path**, and **never commit a game asset, replay, report or pilot
   profile**.
9. A short section names the `project-builder` harness
   (https://github.com/HaroldHormaechea/project-builder) as how this project is
   built and evolved, and explains what `use-cases/` and `use-cases/plans/`
   contain, so a contributor is not puzzled by them.
10. **Every command the guide prints runs as printed**, in PowerShell and in bash,
    from a clone with nothing installed. No command may name a path that varies by
    machine.
11. The guide follows ASD-STE100's writing rules: one instruction per sentence,
    active voice, present tense, consistent terminology, and no word used with two
    meanings. It includes a short list of this project's technical terms and their
    single agreed meaning. **It does not claim ASD-STE100 compliance or
    certification**, because the approved vocabulary is not available to check
    against.
12. The guide does not duplicate `README.md` or `SKILL.md`. Where those already
    answer a question, it links instead of repeating.
13. **(Replaced.)** Source changes are now in scope, limited to the defects and
    reconciliations named in criteria 14–18. No unrelated refactoring.

14. **`cmd_view` uses the selected sim.** `src/fpv_review/cli.py` calls
    `tracks.for_replay(...)` and `scene.load_scene(...)` on the module-level
    Liftoff imports rather than through `sim[...]`, unlike every other command.
    Latent while one sim exists; `view --sim <other>` would silently use Liftoff's
    readers on another sim's data. Fixed to match the pattern the other commands
    already use.

15. **The declared per-sim surface is complete.** `src/fpv_review/sources/__init__.py`
    lists the modules a sim package must provide but omits `capabilities.py`,
    which ADR decision 4 requires and `cli.py` calls. Added.

16. **The ADR's per-sim contract matches what registration actually requires.**
    ADR-0001 names four modules; `cli.py` registers a sim as a ten-key dictionary,
    so a package that conforms to the documented contract does **not** currently
    wire up. Reconcile the two — by correcting the ADR to describe what
    registration really needs, by making registration accept a contract-conformant
    package, or by stating the gap explicitly as work the second sim will force.
    Whichever is chosen, the ADR and the code must agree when this lands, and the
    reasoning goes in the ADR.

17. **The capabilities mechanism is described as it actually behaves.**
    `capabilities.gap()` and `.has()` have no call site: only `declare()` and
    `as_json()` are called. This is correct for Liftoff, which declares no gap that
    suppresses a finding — but the ADR reads as though the naming rule operates
    today. Say plainly that the declaration is recorded and published, and that the
    consuming half is provided for a sim that needs it and is currently unexercised.
    Do not describe unexercised machinery as running.

18. **Nothing in criteria 14–17 changes the tool's output.** The existing four
    saved replays must produce byte-identical `analysis.json`, `report.md`,
    `report.html`, `flight.csv` and SVG assets, apart from timestamps. These are
    corrections to wiring and documentation, not to behaviour.

19. **The guide states the Liftoff requirement up front.** A contributor needs a
    Liftoff install and their own saved replay to verify any change, because
    `flight.csv` is gitignored, no fixture is committed, and the example report
    cannot be regenerated from what the repository contains. State this as a
    prerequisite **early**, where a reader meets it before investing effort — not
    buried in a verification section — and say that **worked examples appear later
    in the guide**, so a reader knows the concrete material is coming rather than
    absent.

## Potential Pitfalls & Open Questions

- **Risk** — A contributor guide that describes the per-sim contract in its own
  words will drift from ADR-0001 the first time the contract changes. Cite and
  link; do not restate. Any duplication is a future falsehood.
- **Risk** — The contract was designed against one sim. ADR-0001 says plainly that
  the first real second sim will change it. The guide must pass that warning on,
  or a contributor will treat a provisional contract as settled.
- **Ambiguity** — "Adding a measurement" has no worked precedent: every existing
  measurement predates the restructure, so the guide describes a path nobody has
  walked. Keep it to what the code structure actually requires, and do not invent
  procedure.
- **Edge case** — A new measurement may need no calibration at all. The guide must
  make the calibration question explicit rather than implying every measurement
  has thresholds.
- **Assumption** — Issue templates, a code of conduct and PR conventions are out
  of scope. The user chose the focused guide; these can follow separately.
- **Risk (added with the widened scope)** — Criterion 16 admits three different
  resolutions, and the cheapest (correct the ADR) is not obviously the best: it
  documents a registration shape nobody designed, whereas making registration
  accept a contract-conformant package is the change that would actually make the
  contract true. Weigh both; do not default to the cheaper one because it is
  smaller. Whatever is chosen must leave the ADR and the code in agreement.
- **Risk (added)** — The code fixes are small and their verification is not: the
  whole point of criterion 18 is that output must not move. The migration's
  baseline apparatus was deleted after UC-01 merged, so this run must re-establish
  a before/after comparison from `main` rather than assume one exists.
- **Edge case (added)** — Criterion 14's defect is unreachable by any test that
  runs today, because only one sim exists. It can be verified by reading and by
  confirming the call now routes through `sim[...]`, not by observing different
  behaviour.
- **Assumption** — The two verification rules this project produced ("a check must
  distinguish 'I looked and found nothing' from 'there was nothing to look at'",
  and "a check nobody has watched fail proves nothing") are deliberately **not**
  included. The user asked for a procedural guide. They remain recorded in
  `use-cases/plans/01-multi-sim-architecture-adr.md`.
- **Missing input** — ASD-STE100's approved vocabulary is in the licensed
  specification and is not available. The writing rules are applied; conformance to
  the word list is unverified and the guide must not imply otherwise.

## Original Description

> After finishing, use ASD STD100 to adjust the CONTRIBUTING guidelines to include
> how to add new elements (sim parsers, measurements) and a link to the
> project-builder harness we are using for this.

## Clarifications

- Q: By "ASD STD100", do you mean ASD-STE100 — Simplified Technical English?
  A: Yes.

- Q: ASD-STE100 has two parts — the writing rules, and an approved vocabulary
  published only in the licensed specification. How should that be treated?
  A: Apply the rules; do not claim compliance.

- Q: Scope of the guide?
  A: The two extension points, plus the constraints, the verification story and
  the harness link. Not a full contributor guide — setup, PR conventions and code
  style would duplicate `README.md` and `SKILL.md`.

- Q: By "measurements", do you mean new derived quantities in the analysis, like
  the existing tilt, sideslip and turn radius?
  A: Yes — new derived quantities. Not new fault classifications.

- Q: Include the two verification rules this run produced?
  A: No. Keep the guide procedural.

- Q: How should the project-builder link be presented?
  A: Named as how this project is built and evolved, so a reader understands what
  `use-cases/` and `use-cases/plans/` are.

- Q: (Discovered during capture) `CONTRIBUTING.md` already exists as a
  placeholder, so this is an edit rather than a new file.
  A: Confirmed by inspection — commit `3b69f5a`, one line, naming the
  rearchitecture that has now merged as its own precondition.

- Q: (After the analyst's first pass) Writing the guide exposed two code defects
  and two ADR overstatements. Fix them here, or defer to a separate use case?
  A: Fix them in this run. The author also asked that the guide state the Liftoff
  install requirement early, and note that worked examples appear later in the
  guide. The run proceeds autonomously — no plan-approval gate for this use case.
