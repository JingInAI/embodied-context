"""Frozen libero published-data adapter."""
from .core import adapt as _adapt

def adapt(export, *, policy, components=None):
    return _adapt('libero', export, policy=policy, components=components)
