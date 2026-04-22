from __future__ import annotations


class OfferQuestError(RuntimeError):
    """Base class for user-facing OfferQuest errors."""


class ProfileValidationError(OfferQuestError):
    """Raised when the extracted candidate profile is too incomplete to trust."""
