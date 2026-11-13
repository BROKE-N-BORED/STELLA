"""STELLA: fine-tune models on your own PC. v0.8.0: make models smaller (re-quantize an installed Ollama model) and teach small models from big ones (distillation), on the command line and through the Chat. Plus v0.7.0 provider connections (Groq, Gemini, or any OpenAI-compatible service with your own key), v0.6.0 provider chat, the v0.4.0 menu + tree + session window, one-click model downloads, built-in How to Use guide, debug log layer."""

from .model import STELLA_VERSION

__version__ = STELLA_VERSION
__all__ = ["__version__"]
