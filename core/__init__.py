"""Shared, module-agnostic infrastructure for the PdM system.

Importing :mod:`core` does not pull in heavy dependencies; submodules are
imported explicitly where needed so that lightweight tooling (e.g. config
inspection) stays fast.
"""
