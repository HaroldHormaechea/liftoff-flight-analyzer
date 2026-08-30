"""One package per sim, each implementing the same surface.

A sim is added by writing a package here - source.py to emit the schema,
map_geometry_generator.py to answer what is around a point, calibration.py for
the constants measured on that sim - and by registering it in cli.py. The
analysis is not touched.

No stub packages exist for sims whose data nobody has inspected: the required
surface is documented in docs/adr/0001-multi-sim-architecture.md instead.
"""
