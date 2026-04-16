"""多人格系统"""
from .models import (
    PersonaConfig, PersonaSoul, PersonaStyle,
    SharedMemory, PersonaIndex, SessionState
)
from .manager import PersonaManager

__all__ = [
    "PersonaManager",
    "PersonaConfig",
    "PersonaSoul",
    "PersonaStyle",
    "SharedMemory",
    "PersonaIndex",
    "SessionState"
]
