"""Frozen isaac_lab_arena published-data adapter."""
from .core import adapt as _adapt

def adapt(export, *, policy, components=None):
    return _adapt('isaac_lab_arena', export, policy=policy, components=components)
