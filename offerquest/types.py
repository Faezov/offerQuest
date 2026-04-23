from __future__ import annotations

from typing import Any, TypeAlias

# OfferQuest payloads are JSON-like dictionaries that are enriched across modules.
# Keep these aliases broad until the payload boundaries are ready for strict schemas.
JobRecord: TypeAlias = dict[str, Any]
CandidateProfile: TypeAlias = dict[str, Any]
ScoredJob: TypeAlias = dict[str, Any]
ATSReport: TypeAlias = dict[str, Any]
