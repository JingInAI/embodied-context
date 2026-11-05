"""Frozen vlabench published-data adapter."""
from .core import adapt as _adapt

def adapt(export, *, policy, components=None):
    return _adapt('vlabench', export, policy=policy, components=components)
