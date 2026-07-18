"""The brain — orchestrator loop (§13), dialog window (§19), persona (§33 base)."""
from .dialog import DialogWindow  # noqa: F401
from .persona import build_system_prompt  # noqa: F401
from .loop import BrainLoop  # noqa: F401
