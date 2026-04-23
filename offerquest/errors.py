from __future__ import annotations


class OfferQuestError(RuntimeError):
    """Base class for user-facing OfferQuest errors."""


class ConfigError(OfferQuestError):
    """Raised when OfferQuest configuration cannot be loaded or validated."""


class JobSourceError(OfferQuestError):
    """Raised when a job source fetch or refresh operation fails."""


class DocumentExtractionError(OfferQuestError):
    """Raised when OfferQuest cannot extract readable text from a document."""


class OllamaError(OfferQuestError):
    """Raised when an Ollama request fails."""


class ProfileValidationError(OfferQuestError):
    """Raised when the extracted candidate profile is too incomplete to trust."""
