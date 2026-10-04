"""The copy engine: owns copy logic, engine state (`data/engine-<address>.db`, per trading account), the
event log (`data/events.jsonl`) and the worker loop.

Public contract (what every other service may import): `engine.public` and
`engine.sizing`. Nothing else in this package is part of the contract --
`core.py`, `state.py`, `events.py` and `settings_io.py` are internals and
may change shape without notice. See services/engine/README.md.
"""
