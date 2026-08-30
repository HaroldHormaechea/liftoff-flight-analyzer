"""Sim-agnostic: the schema, the analysis, the report and the incident view.

Nothing here may import from fpv_review.sources. Anything a stage needs from a
particular sim - a calibrated threshold, a decoded flight, track geometry - is
passed in by cli.py as a parameter or a callable.
"""
