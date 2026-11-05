"""Frozen libero_plus published-data adapter."""
from .core import adapt as _adapt

def adapt(export, *, policy, components=None):
    return _adapt('libero_plus', export, policy=policy, components=components)
