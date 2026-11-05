"""Frozen robotwin2 published-data adapter."""
from .core import adapt as _adapt

def adapt(export, *, policy, components=None):
    return _adapt('robotwin2', export, policy=policy, components=components)
