#!/usr/bin/env python3
"""
liftoff_view.py - a 3D view of an incident: geometry, flight path, orbit, scrub.

This is a command and a library. Run it and it writes one standalone,
self-contained page for one moment. Import it and `fpv_report.py` uses the same
`build()` and the same `VIEWER_JS` for the recording behind every crash and
every stall in a report, so the renderer exists once and a fix to it lands in
both.

    python liftoff_view.py --replay replays/<file>.xml --at 6.0 -o crash.html

What it draws:

  * the environment's collision geometry, culled to a radius around the path
    (from `liftoff_scene.py`'s cache)
  * the TRACK PROPS near the incident, drawn as placeholders - see below
  * the flown path, coloured by speed
  * the quad at its true attitude, with a nose arrow, on a time scrubber
  * every impact found in the window, marked

Drag to orbit, wheel to zoom, drag the scrubber or press play.

WHY THE PROPS ARE PLACEHOLDERS
------------------------------
A track's props - ramps, barriers, arches - are placed by the Track XML and
instantiated from prefabs at runtime. They are NOT baked into the scene bundle,
so the scene cache does not contain them. Their POSITION and ROTATION are known
exactly; only their SHAPE is missing, because that lives in a prefab bundle that
is not extracted yet.

This matters more than it sounds: the crash this was built against hit a ramp
and a crowd-control barrier 2.3 m away, and nothing in the scene geometry is
within 8 m of the impact. Drawn from the scene alone, that crash looks like the
quad stopping in clear air. So props are drawn at their true position and yaw
with a NOMINAL size, in a different colour, and clearly labelled - a marker
saying "something is here", not a claim about what it looks like.

IMPACTS ARE DETECTED, NOT READ
------------------------------
The replay's `isCrashed` flag is unreliable - it reads false on a flight that
ends with the quad pinned against the ground at full throttle. So an impact is
found from the trajectory instead: a large speed drop inside one or two samples.
That signature caught both impacts in the reference crash, 0.7 s apart, where
the flag caught neither.
"""

import json
import math
import os
import sys

from fpv_review.common import geometry


def impacts(rows, drop_kmh, debounce):
    """Sample indices where speed collapses - an impact, not braking.

    Braking bleeds a few km/h per sample; hitting something takes 20+ out in one.
    Reported once per event, not once per sample, so a two-sample collapse is one
    impact.

    `drop_kmh` and `debounce` come from the sim's calibration, not from here:
    both are tied to the sample rate, and a sim recording at 100 Hz spreads the
    same collision over ten samples."""
    found, last = [], -99
    for i in range(1, len(rows)):
        drop = rows[i - 1][16] - rows[i][16]
        if drop >= drop_kmh and i - last > debounce:
            found.append(i)
            last = i
    return found


# ---------------------------------------------------------------------------
# the viewer
#
# One factory function, not a script, because the report page opens several
# recordings from one modal and the standalone page opens exactly one. Both get
# the same renderer from the same string: a fix to the projection, the shading
# or the playback lands in both by construction.
#
# It binds to `data-fpv` attributes inside the element it is handed rather than
# to ids, so a page may hold as many viewers as it likes and none of them has
# to know what the others called their buttons.
# ---------------------------------------------------------------------------

VIEWER_JS = r"""
function fpvViewer(root, D){
  const el = n => root.querySelector('[data-fpv="' + n + '"]');
  const cv = el('canvas'), cx = cv.getContext('2d');
  const scrub = el('scrub'), playBtn = el('play'), gatesBtn = el('gates'),
        trigBtn = el('triggers'), readout = el('readout'), timeOut = el('time');
  let yaw = 2.3, pitch = 0.45, dist = D.dist0, frame = D.startFrame | 0;
  let playing = false, timer = null, alive = true;
  /* Route checkpoints and pit volumes are both OFF by default: neither is an
     obstacle, and the question this view answers is what the quad hit. They
     are one button away when the route itself is what you want to see. */
  let showTriggers = !!D.showTriggers, showGates = !!D.showGates;
  const tgt = D.target.slice();

  /* The canvas is measured, never told: it fills whatever box the page gives
     it - the whole window on the standalone page, a modal stage in the report -
     and a ResizeObserver catches the modal opening, which fires no resize
     event on the window. */
  function resize(){
    const r = cv.getBoundingClientRect();
    const w = Math.max(1, Math.round(r.width || cv.clientWidth || 640));
    const h = Math.max(1, Math.round(r.height || cv.clientHeight || 360));
    cv.width = Math.round(w * devicePixelRatio);
    cv.height = Math.round(h * devicePixelRatio);
    draw();
  }

  /* Unity is LEFT-handed (+Y up), so the camera basis uses right = up x forward.
     Using the right-handed cross product here mirrors the whole scene, which is
     subtly wrong in a way that is hard to spot and impossible to unsee. */
  function basis(){
    const cp = Math.cos(pitch), sp = Math.sin(pitch);
    const cam = [tgt[0] - dist*cp*Math.cos(yaw), tgt[1] + dist*sp, tgt[2] - dist*cp*Math.sin(yaw)];
    let f = [tgt[0]-cam[0], tgt[1]-cam[1], tgt[2]-cam[2]];
    const fl = Math.hypot(f[0],f[1],f[2]); f = f.map(v=>v/fl);
    let r = [ 1*f[2] - 0*f[1], 0*f[0] - 0*f[2], 0*f[1] - 1*f[0] ];   // up(0,1,0) x f
    const rl = Math.hypot(r[0],r[1],r[2]) || 1; r = r.map(v=>v/rl);
    const u = [ f[1]*r[2]-f[2]*r[1], f[2]*r[0]-f[0]*r[2], f[0]*r[1]-f[1]*r[0] ];
    return {cam, f, r, u};
  }
  function project(p, B, W, H, focal){
    const v = [p[0]-B.cam[0], p[1]-B.cam[1], p[2]-B.cam[2]];
    const z = v[0]*B.f[0]+v[1]*B.f[1]+v[2]*B.f[2];
    if (z <= 0.05) return null;
    const x = v[0]*B.r[0]+v[1]*B.r[1]+v[2]*B.r[2];
    const y = v[0]*B.u[0]+v[1]*B.u[1]+v[2]*B.u[2];
    return [W/2 + focal*x/z, H/2 - focal*y/z, z];
  }
  function qrot(q, v){
    const x = q[0], y = q[1], z = q[2], w = q[3];
    const cx1 = y*v[2]-z*v[1], cy1 = z*v[0]-x*v[2], cz1 = x*v[1]-y*v[0];
    return [ v[0] + 2*(w*cx1 + y*cz1 - z*cy1),
             v[1] + 2*(w*cy1 + z*cx1 - x*cz1),
             v[2] + 2*(w*cz1 + x*cy1 - y*cx1) ];
  }
  function qmul(a, b){
    return [ a[3]*b[0] + a[0]*b[3] + a[1]*b[2] - a[2]*b[1],
             a[3]*b[1] - a[0]*b[2] + a[1]*b[3] + a[2]*b[0],
             a[3]*b[2] + a[0]*b[1] - a[1]*b[0] + a[2]*b[3],
             a[3]*b[3] - a[0]*b[0] - a[1]*b[1] - a[2]*b[2] ];
  }
  const CUBE = [[-1,-1,-1],[1,-1,-1],[1,1,-1],[-1,1,-1],[-1,-1,1],[1,-1,1],[1,1,1],[-1,1,1]];
  const FACES = [[0,1,2,3],[5,4,7,6],[4,0,3,7],[1,5,6,2],[3,2,6,7],[4,5,1,0]];

  function boxFaces(centre, half, q, colour){
    const pts = CUBE.map(c => {
      let l = [c[0]*half[0], c[1]*half[1], c[2]*half[2]];
      if (q) l = qrot(q, l);
      return [centre[0]+l[0], centre[1]+l[1], centre[2]+l[2]];
    });
    return FACES.map(f => ({pts: f.map(i=>pts[i]), colour}));
  }
  function shade(hex, k){
    const n = parseInt(hex.slice(1),16);
    const r = Math.min(255,(n>>16&255)*k)|0, g = Math.min(255,(n>>8&255)*k)|0, b = Math.min(255,(n&255)*k)|0;
    return 'rgb('+r+','+g+','+b+')';
  }
  const LIGHT = (function(){ const v=[0.4,0.85,0.3], l=Math.hypot(v[0],v[1],v[2]);
                             return v.map(x=>x/l); })();
  function normal(p){
    const a=[p[1][0]-p[0][0],p[1][1]-p[0][1],p[1][2]-p[0][2]];
    const b=[p[2][0]-p[0][0],p[2][1]-p[0][1],p[2][2]-p[0][2]];
    const n=[a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]];
    const l=Math.hypot(n[0],n[1],n[2])||1; return n.map(v=>v/l);
  }
  function ramp(v){
    const k = Math.max(0, Math.min(1, v / D.vref));
    return k < 0.5 ? 'rgb('+(240)+','+(82+120*k*2)+','+(77+20*k*2)+')'
                   : 'rgb('+(240-163*(k-0.5)*2)+','+(202+6*(k-0.5)*2)+','+(97+102*(k-0.5)*2)+')';
  }

  function draw(){
    const W = cv.width, H = cv.height, focal = H * 0.9;
    const B = basis();
    cx.fillStyle = D.bg || '#0e1116'; cx.fillRect(0,0,W,H);

    const polys = [];
    for (const c of D.colliders){
      if (c.t === 'box') polys.push(...boxFaces(c.p, c.s, c.q, '#5b6b7f'));
      else if (c.t === 'cap'){
        const h = [c.r, c.r, c.r]; h[c.a] = Math.max(c.h/2, c.r);
        polys.push(...boxFaces(c.p, h, c.q, '#556077'));
      } else polys.push(...boxFaces(c.p, [c.r,c.r,c.r], null, '#556077'));
    }
    for (const p of D.props){
      if (p.k === 'trigger' && !showTriggers) continue;
      if (p.k === 'gate' && !showGates) continue;
      const a = p.yaw * Math.PI/180, s = Math.sin(a/2), cc = Math.cos(a/2);
      const q = [0,s,0,cc];
      const colour = p.k === 'gate' ? '#4dd0c7' : p.k === 'trigger' ? '#3a4a5c' : '#e3b341';
      if (p.sh && p.sh.length){
        /* Real prefab colliders, in the item's own frame: an instance is only ever
           the Track XML's position and yaw applied to that shape. */
        for (const c of p.sh){
          const l = c.p ? qrot(q, c.p) : [0,0,0];
          const w = [p.p[0]+l[0], p.p[1]+l[1], p.p[2]+l[2]];
          if (c.t === 'mesh'){
            /* Real triangles. A ramp's hull is two of them; its bounding box would
               be a slab with two vertical walls the game does not have. */
            for (const f of c.f){
              polys.push({pts: f.map(i => {
                const lv = qrot(q, c.v[i]);
                return [p.p[0]+lv[0], p.p[1]+lv[1], p.p[2]+lv[2]];
              }), colour: colour, twoSided: true});
            }
            continue;
          }
          if (c.t === 'box')      polys.push(...boxFaces(w, c.s, qmul(q, c.q), colour));
          else if (c.t === 'sph') polys.push(...boxFaces(w, [c.r,c.r,c.r], q, colour));
          else { const h = [c.r,c.r,c.r]; h[c.a] = Math.max(c.h/2, c.r);
                 polys.push(...boxFaces(w, h, qmul(q, c.q), colour)); }
        }
      } else {
        /* Shape unknown - a mesh-only prefab. Drawn dimmer: a marker saying
           something is here, not a claim about what it looks like. */
        polys.push(...boxFaces(p.p, D.propSize, q, p.k === 'prop' ? '#8a6d2f' : colour));
      }
    }

    const drawable = [];
    for (const poly of polys){
      const sp = poly.pts.map(p => project(p, B, W, H, focal));
      if (sp.some(p => !p)) continue;
      const ax = sp[1][0]-sp[0][0], ay = sp[1][1]-sp[0][1];
      const bx = sp[2][0]-sp[0][0], by = sp[2][1]-sp[0][1];
      const facing = ax*by - ay*bx;
      if (facing <= 0 && !poly.twoSided) continue;           // back face
      if (facing === 0) continue;                            // edge-on, no area
      const n = normal(poly.pts);
      const lit = 0.45 + 0.55*Math.abs(n[0]*LIGHT[0]+n[1]*LIGHT[1]+n[2]*LIGHT[2]);
      drawable.push({sp: sp, z: sp.reduce((a,p)=>a+p[2],0)/sp.length,
                     fill: shade(poly.colour, lit)});
    }
    drawable.sort((a,b)=>b.z-a.z);
    cx.lineWidth = devicePixelRatio;
    for (const d of drawable){
      cx.beginPath(); cx.moveTo(d.sp[0][0], d.sp[0][1]);
      for (let i=1;i<d.sp.length;i++) cx.lineTo(d.sp[i][0], d.sp[i][1]);
      cx.closePath(); cx.fillStyle = d.fill; cx.fill();
      cx.strokeStyle = 'rgba(0,0,0,.45)'; cx.stroke();
    }

    // flight path, coloured by speed
    cx.lineWidth = 3*devicePixelRatio; cx.lineCap = 'round';
    for (let i=1;i<D.path.length;i++){
      const a = project(D.path[i-1].p, B, W, H, focal), b = project(D.path[i].p, B, W, H, focal);
      if (!a || !b) continue;
      cx.beginPath(); cx.moveTo(a[0],a[1]); cx.lineTo(b[0],b[1]);
      cx.strokeStyle = ramp(D.path[i].v); cx.globalAlpha = i <= frame ? 1 : 0.28; cx.stroke();
    }
    cx.globalAlpha = 1;

    for (const i of D.impacts){
      const p = project(D.path[i].p, B, W, H, focal);
      if (!p) continue;
      const rr = Math.max(6, 260/p[2]) * devicePixelRatio;
      cx.beginPath(); cx.arc(p[0],p[1],rr,0,7); cx.strokeStyle='#f0524d';
      cx.lineWidth=2.5*devicePixelRatio; cx.stroke();
      cx.beginPath(); cx.arc(p[0],p[1],rr*0.34,0,7); cx.fillStyle='#f0524d'; cx.fill();
    }

    // the quad: a small body at its true attitude, plus a nose arrow
    const s = D.path[frame];
    for (const poly of boxFaces(s.p, [0.16,0.06,0.16], s.q, '#e6edf3')){
      const sp = poly.pts.map(p=>project(p,B,W,H,focal));
      if (sp.some(p=>!p)) continue;
      cx.beginPath(); cx.moveTo(sp[0][0],sp[0][1]);
      for (let i=1;i<sp.length;i++) cx.lineTo(sp[i][0],sp[i][1]);
      cx.closePath(); cx.fillStyle='#e6edf3'; cx.fill();
    }
    const nose = qrot(s.q, [0,0,1.4]);
    const a = project(s.p, B, W, H, focal);
    const b = project([s.p[0]+nose[0], s.p[1]+nose[1], s.p[2]+nose[2]], B, W, H, focal);
    if (a && b){
      cx.beginPath(); cx.moveTo(a[0],a[1]); cx.lineTo(b[0],b[1]);
      cx.strokeStyle='#4dd0c7'; cx.lineWidth=3*devicePixelRatio; cx.stroke();
    }
    if (readout) readout.textContent = s.v.toFixed(0)+' km/h   height '+s.p[1].toFixed(2)+' m';
    if (timeOut) timeOut.textContent = 't = '+s.t.toFixed(1)+' s';
  }

  function seek(f){
    frame = Math.max(0, Math.min(D.path.length-1, f|0));
    if (scrub) scrub.value = frame;
    draw();
  }
  function setPlaying(on){
    playing = !!on;
    if (playBtn) playBtn.textContent = playing ? 'Pause' : 'Play';
    if (timer){ clearTimeout(timer); timer = null; }
    if (playing) tick();
  }
  function tick(){
    if (!playing || !alive) return;
    /* A recording sitting on its last frame and asked to play again starts
       over rather than doing nothing. */
    frame = (frame + 1) % D.path.length;
    if (scrub) scrub.value = frame;
    draw();
    timer = setTimeout(()=>requestAnimationFrame(tick), 90);
  }

  if (scrub){
    scrub.max = D.path.length - 1; scrub.value = frame;
    scrub.addEventListener('input', ()=>{ setPlaying(false); seek(+scrub.value); });
  }
  if (playBtn) playBtn.addEventListener('click', ()=>setPlaying(!playing));
  if (gatesBtn){
    gatesBtn.textContent = showGates ? 'Hide route' : 'Show route';
    gatesBtn.addEventListener('click', ()=>{
      showGates = !showGates;
      gatesBtn.textContent = showGates ? 'Hide route' : 'Show route'; draw();
    });
  }
  if (trigBtn){
    trigBtn.textContent = showTriggers ? 'Hide triggers' : 'Show triggers';
    trigBtn.addEventListener('click', ()=>{
      showTriggers = !showTriggers;
      trigBtn.textContent = showTriggers ? 'Hide triggers' : 'Show triggers'; draw();
    });
  }
  if (playBtn) playBtn.textContent = 'Play';

  let drag = null;
  cv.addEventListener('pointerdown', e => { drag = [e.clientX, e.clientY];
    cv.classList.add('drag'); cv.setPointerCapture(e.pointerId); });
  cv.addEventListener('pointerup', () => { drag = null; cv.classList.remove('drag'); });
  cv.addEventListener('pointermove', e => {
    if (!drag) return;
    yaw += (e.clientX - drag[0]) * 0.008;
    pitch = Math.max(-1.4, Math.min(1.4, pitch + (e.clientY - drag[1]) * 0.006));
    drag = [e.clientX, e.clientY]; draw();
  });
  cv.addEventListener('wheel', e => {
    e.preventDefault();
    dist = Math.max(2, Math.min(400, dist * (e.deltaY > 0 ? 1.12 : 0.89))); draw();
  }, {passive:false});

  const ro = typeof ResizeObserver === 'function' ? new ResizeObserver(()=>resize()) : null;
  if (ro) ro.observe(cv);
  addEventListener('resize', resize);
  resize();

  return {
    draw: draw, resize: resize, seek: seek,
    play: ()=>setPlaying(true), pause: ()=>setPlaying(false),
    /* Closing a modal must stop the loop it started. Without this, every
       recording ever opened keeps drawing into a detached canvas. */
    destroy: function(){
      alive = false; playing = false;
      if (timer){ clearTimeout(timer); timer = null; }
      if (ro) ro.disconnect();
      removeEventListener('resize', resize);
    }
  };
}
"""


PAGE = """<title>__TITLE__</title>
<style>
  :root { color-scheme: dark; }
  body { margin:0; background:#0e1116; color:#c9d1d9;
         font:13px/1.5 ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif; }
  #wrap { position:relative; width:100vw; height:100vh; overflow:hidden; }
  canvas { display:block; width:100%; height:100%; cursor:grab; }
  canvas.drag { cursor:grabbing; }
  #hud { position:absolute; top:12px; left:14px; pointer-events:none;
         text-shadow:0 1px 3px #000; }
  #hud b { color:#e6edf3; font-size:15px; }
  #hud .k { color:#8b949e; }
  #legend { position:absolute; top:12px; right:14px; text-align:right;
            pointer-events:none; text-shadow:0 1px 3px #000; }
  #legend i { display:inline-block; width:10px; height:10px; margin-right:6px;
              vertical-align:middle; border-radius:2px; }
  #bar { position:absolute; left:0; right:0; bottom:0; padding:10px 14px 14px;
         background:linear-gradient(transparent,#0e1116cc 40%); display:flex;
         gap:12px; align-items:center; }
  #bar input[type=range] { flex:1; accent-color:#4dd0c7; }
  button { background:#21262d; color:#c9d1d9; border:1px solid #30363d;
           border-radius:6px; padding:5px 12px; font:inherit; cursor:pointer; }
  button:hover { background:#30363d; }
  #t { font-variant-numeric:tabular-nums; min-width:112px; }
  .warn { color:#e3b341; }
  .k2 { color:#8b949e; }
</style>
<div id=wrap>
  <canvas data-fpv=canvas></canvas>
  <div id=hud>
    <b>__HEADING__</b><br>
    <span class=k>drag to orbit &middot; wheel to zoom</span><br>
    <span data-fpv=readout class=k></span>
  </div>
  <div id=legend>
    <span><i style="background:#5b6b7f"></i>scene collider</span><br>
    <span><i style="background:#e3b341"></i>solid track prop <span class=warn>(placeholder shape)</span></span><br>
    <span><i style="background:#4dd0c7"></i>route checkpoint</span><br>
    <span><i style="background:#3a4a5c"></i>pit trigger <span class=k2>(not solid, hidden)</span></span><br>
    <span><i style="background:#f0524d"></i>impact</span>
  </div>
  <div id=bar>
    <button data-fpv=play>Play</button>
    <input data-fpv=scrub type=range min=0 max=0 step=1 value=0>
    <span data-fpv=time id=t></span>
    <button data-fpv=gates>Show route</button>
    <button data-fpv=triggers>Show triggers</button>
  </div>
</div>
<script>
__VIEWER_JS__
fpvViewer(document.getElementById('wrap'), __DATA__);
</script>
"""


def window_indices(rows, at, pad):
    """The sample indices within `pad` seconds of `at` -> (i0, i1), or None."""
    t0 = rows[0][0]
    idx = [i for i, r in enumerate(rows) if at - pad <= r[0] - t0 <= at + pad]
    return (idx[0], idx[-1] + 1) if idx else None


def window_points(rows, i0, i1):
    """The (t, position) samples of one incident window, clocked from flight start.

    Exposed rather than kept inside build(), because the caller has to ask the
    sim's map geometry generator what is near the SAME points. Deriving them a
    second way at the call site is how the geometry and the path drift apart."""
    window = rows[i0:i1]
    if not window:
        raise ValueError("empty incident window")
    t0 = rows[0][0]
    return [(r[0] - t0, (r[1], r[2], r[3])) for r in window]


def build(rows, i0, i1, focus=None, radius=25.0, props=None, prop_size=None,
          scene=None, hits=None, show_gates=True, show_triggers=False, note=""):
    """Everything one recording needs, as a plain dict the viewer reads.

    Every geometry source is optional, and a missing one simply does not draw.
    That is the difference between a view that works on the two environments
    whose scene bundles happen to be cached and one that works on every flight:
    the path, the attitude and the impacts come from the replay alone, and they
    are most of the answer. `note` is what the page says about the rest.

    `props` arrives as data from the sim's map geometry generator, and
    `prop_size` from its calibration. Neither is looked up here: this module
    draws, and reaching into a sim to find out what to draw is what would make
    common/ depend on sources/."""
    if prop_size is None:
        raise TypeError("build() needs prop_size from the sim's calibration")
    points = window_points(rows, i0, i1)
    window = rows[i0:i1]
    t0 = rows[0][0]
    kept = geometry.cull(scene, points, radius) if scene else []

    focus = i0 + (i1 - i0) // 2 if focus is None else min(max(focus, i0), i1 - 1)
    centre = list(rows[focus][1:4])
    speeds = [r[16] for r in rows]
    data = {
        "colliders": kept,
        "props": props or [],
        "propSize": list(prop_size),
        "path": [{"t": round(r[0] - t0, 2),
                  "p": [round(r[1], 3), round(r[2], 3), round(r[3], 3)],
                  "q": [round(r[4], 4), round(r[5], 4), round(r[6], 4), round(r[7], 4)],
                  "v": round(r[16], 1)} for r in window],
        "impacts": [i - i0 for i in (hits or []) if i0 <= i < i1],
        "target": [round(v, 2) for v in centre],
        # Fit the camera to the PATH, not to the cull radius. At racing speed a
        # three-second window is ninety metres long, so a camera placed at the
        # radius sits inside the flight and half of it swings off screen.
        "dist0": round(min(140.0, max(15.0, 1.7 * max(
            math.dist(centre, (r[1], r[2], r[3])) for r in window))), 1),
        "vref": max(30.0, sorted(speeds)[int(len(speeds) * 0.9)]),
        "startFrame": 0,
        "showGates": bool(show_gates),
        "showTriggers": bool(show_triggers),
        "note": note,
    }
    if data["impacts"]:
        data["startFrame"] = max(0, data["impacts"][0] - 3)
    return data


def page(data, title, heading):
    """The standalone, one-incident page."""
    return (PAGE.replace("__TITLE__", title)
                .replace("__HEADING__", heading)
                .replace("__VIEWER_JS__", VIEWER_JS)
                .replace("__DATA__", json.dumps(data, separators=(",", ":"))))
