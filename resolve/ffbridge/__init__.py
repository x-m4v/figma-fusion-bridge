"""Figma Fusion Bridge — Fusion side.

This package is deliberately split in two halves:

* Everything that converts a design document into a Fusion node graph is pure
  Python with no imports from Resolve, Fusion or the network. It is a function
  from JSON to text, so all of it — coordinates, colour, gradients, stroke
  geometry, blend modes — is covered by ordinary unit tests that run anywhere.

* Only :mod:`ffbridge.applier` and :mod:`ffbridge.client` touch the outside
  world, and they are thin.

That split is what makes the maths verifiable, which matters more here than
usual: a one-axis sign error in a coordinate mapper is invisible in a demo and
obvious in production.
"""

__version__ = "0.1.0"
SCHEMA_VERSION = "1.0.0"

__all__ = ["__version__", "SCHEMA_VERSION"]
