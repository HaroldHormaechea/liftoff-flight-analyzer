# The manoeuvre library

`manoeuvres/` holds eight freestyle manoeuvres, pre-rendered with the same code
that draws a flight: `common/report.py`'s figure primitives for the flat SVG and
`common/incident_view.py` for the orbitable 3D view. A manoeuvre figure and a lap
figure are therefore the same picture, in the same colours, on the same speed
ramp.

They exist for one reason. A debrief regularly has to name a manoeuvre the pilot
has **not flown yet** — a split-S as the way out of a corner too tight to bank
in, a power loop as what the tree was for — and describing the shape of one in
prose is strictly worse than showing it. `manoeuvres/README.md` is the generated
inventory; this file is the guidance.

## What they are, and what they are not

Synthetic. Each is a parametric trajectory — position and attitude at 10 Hz —
not a recording. That is the whole reason they can be committed, unlike anything
under `reports/` or `replays/`.

Two properties keep them honest when they sit next to measured data:

- **Speed is derived** from the path by finite difference, never asserted, so the
  colour ramp means on these figures exactly what it means on a real recording.
- **Stick positions are not modelled**, and are left at zero rather than
  invented. A synthetic throttle trace sitting in the same schema as a measured
  one is a trap: everything else in a report is evidence, and a reader has no way
  to tell which is which.

They are generated, never hand-edited. `python manoeuvres/build_manoeuvres.py`
rewrites the whole folder, its README included, in about a second.

## Putting one in a report

**Copy the figure into the report's own `assets/`.** Reports do not live in this
repo — when the toolkit is mounted as a skill they live in the host project — so
a relative href from a report back to `manoeuvres/` is different for every
installation and long enough to get wrong once and then copy forward. Copying
keeps the report folder portable, which is what every other figure in it already
is. Regenerating a report writes into `assets/` but never clears it, so the copy
survives a rebuild.

```bash
python manoeuvres/build_manoeuvres.py --install <report-dir> backflip split-s
# assets/backflip.svg
# assets/split-s.svg
```

Then, inside the Debrief in `report.md`:

```markdown
![Backflip](assets/backflip.svg)
```

That renders in `report.md` on GitHub and in a VS Code preview, and in the
generated `report.html`, with nothing further to do.

**When to reach for one.** When the debrief names a manoeuvre the pilot has not
flown, or is being taught. Not as decoration on a manoeuvre they already own —
a figure next to a fault they have already fixed reads as padding, and the
report is short on purpose.

## The interactive view

`report.html` can carry the orbitable version too. Put `viewer.js`,
`manoeuvres.css` and the fragment where the page can reach them:

```html
<link rel="stylesheet" href="manoeuvres.css">
<script>window.__fpvViewerSrc = 'viewer.js';</script>
<!-- paste split-s.fragment.html here -->
```

Fragments look their host up by `id` rather than by `document.currentScript`,
which is null whenever a script is re-executed after insertion rather than run by
the parser — a host that re-injects the page body would otherwise leave the
viewer dead with no error. They are self-registering: the first fragment on a
page loads `viewer.js` and the rest queue behind it, so any number can share one
page. `<slug>.bare.html` is the same markup and data with no script at all, for a
page that would rather initialise every viewer itself in one pass.

### Two traps, both learned the hard way

**Pass the whole section as the viewer's root.** `fpvViewer(root, data)` finds
every control with `root.querySelector('[data-fpv="..."]')`, and `play`, `scrub`
and `time` live in `.fpv-bar`, a **sibling** of `.fpv-stage`. Hand it
`<section class="fpv-man">`. Hand it the stage instead and the canvas and the
readout bind, the view renders perfectly, and the transport is silently dead —
which looks like a broken page for reasons nothing on screen explains.

**Do not hide a viewer inside a collapsed `<details>` on a page you do not
control the height of.** The viewer measures its canvas and a `ResizeObserver`
catches the expansion, so the drawing is fine — but a host that sizes an iframe
to the content at load will not extend its scroll area when the section opens,
and the stage ends up below anything the reader can reach.

## Reading the figure

Path coloured by speed, on the report's ramp. The bar across the path is the
airframe and the spike is the top of the quad; both turn red once the quad is
inverted. That is the point of the drawing — it makes "which way is up"
answerable at a glance, which is the exact question a pilot who has never flown
inverted cannot yet answer in the air.

Loops are drawn side-on and the flat manoeuvres from above, because a loop seen
from above is a straight line. The projection is chosen per manoeuvre in
`MANOEUVRES`, not guessed at render time.

## Adding one

Write a function returning `[(pos, forward, up), ...]` and add a row to
`MANOEUVRES` with its slug, projection, title and note. `series()` turns the
frames into `FlightSample`s, deriving speed and building the attitude quaternion
from the basis.

The frame is right-handed, Y up, body forward `+Z`, body up `+Y`, body right
`+X = cross(up, forward)` — verified against a real replay, and the same
convention `incident_view.js` assumes.

`loop_frames()` carries the one piece of geometry worth knowing: **thrust points
at the centre of the loop the whole way round**, which is what makes a loop a
loop and why the throttle goes up over the top rather than off. Its `turns`
argument carries direction — positive sweeps the radial from up toward forward
(start at the top and pull down through: a split-S), negative sweeps it the other
way (start at the bottom and pull back over: a flip or a power loop). The tangent
is `d(radial)/d(theta)` and flips sign with it. Getting that wrong is what made
the first backflip start inverted and the first split-S come out flying the way
it went in, and neither was obvious from the numbers — only from the picture.
