"""Property-based invariants (hypothesis). These catch numbers that are
plausible-looking but WRONG: nothing crashes, a page just shows a figure
that cannot be true.

Profiles (HYPOTHESIS_PROFILE env var):
  gate (default)  bounded example counts, derandomized: part of `make test`,
                  deterministic, the whole dir runs in a few seconds.
  deep            many examples, random seeds: `make invariants-deep` before
                  a release or after touching sizing / sim math.
"""
from __future__ import annotations

import os

from hypothesis import HealthCheck, settings

settings.register_profile(
    "gate", max_examples=40, deadline=None, derandomize=True, print_blob=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much])
settings.register_profile(
    "deep", max_examples=1500, deadline=None, print_blob=True,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.data_too_large, HealthCheck.filter_too_much])
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "gate"))
