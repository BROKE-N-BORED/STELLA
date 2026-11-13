"""STELLA: fine-tune models on your own PC. v0.6.0: provider chat (an AI chat that sets up and runs training, with the model-agnostic training template), plus the v0.4.0 menu + tree + session window, one-click model downloads, built-in How to Use guide, debug log layer."""

from .model import STELLA_VERSION

__version__ = STELLA_VERSION
__all__ = ["__version__"]
