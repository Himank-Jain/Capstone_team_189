"""Test bootstrap that forces the repository checkout to win over any installed package
with the same top-level module names (for example, a stray site-packages `phase3`).
"""
import os
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Remove any shadowing module instance before importing project modules.
for name in list(sys.modules):
    if name == "phase3" or name.startswith("phase3."):
        del sys.modules[name]
