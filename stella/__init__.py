"""STELLA v0.29.0: fine-tune models on your own PC.

Train a small model on your own data, sleep on it, probe it, and
export it — through the window or the command line. (R127: the
versioned feature list that used to live here is gone — it
drifted with every release and said v0.8.0 while the app was
v0.28.0. CHANGELOG.md is the version record.)"""

from .model import STELLA_VERSION

__version__ = STELLA_VERSION
__all__ = ["__version__"]
