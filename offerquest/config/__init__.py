from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..errors import ConfigError

DEFAULTS_PATH = Path(__file__).parent / "defaults.json"
CONFIG_PATH_ENVVAR = "OFFERQUEST_CONFIG"


@dataclass(frozen=True)
class Config:
    skill_patterns: dict[str, list[str]]
    domain_patterns: dict[str, list[str]]
    role_families: dict[str, list[str]]
    role_penalties: dict[str, int]
    location_primary_terms: tuple[str, ...]
    location_remote_terms: tuple[str, ...]
    location_secondary_terms: tuple[str, ...]
    location_state_codes: frozenset[str]
    location_general_terms: frozenset[str]
    ats_extra_patterns: dict[str, list[str]]
    ats_section_headings: tuple[str, ...]
    ats_required_markers: tuple[str, ...]
    ats_keyword_weight: float
    ats_required_weight: float
    search_focus_skill_to_keyword: dict[str, str]
    search_focus_domain_to_keyword: dict[str, str]
    search_focus_default_title: str
    search_focus_titles_by_skill: dict[str, list[str]]
    search_focus_titles_by_domain: dict[str, list[str]]
    search_focus_stretch_roles: tuple[str, ...]
    fallback_resume_title: str


def _deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _config_from_dict(data: dict[str, Any]) -> Config:
    location = data["location"]
    ats = data["ats"]
    search_focus = data["search_focus"]
    return Config(
        skill_patterns=data["skill_patterns"],
        domain_patterns=data["domain_patterns"],
        role_families=data["role_families"],
        role_penalties=data["role_penalties"],
        location_primary_terms=tuple(location["primary_terms"]),
        location_remote_terms=tuple(location["remote_terms"]),
        location_secondary_terms=tuple(location["secondary_terms"]),
        location_state_codes=frozenset(location["state_codes"]),
        location_general_terms=frozenset(location["general_terms"]),
        ats_extra_patterns=ats["extra_patterns"],
        ats_section_headings=tuple(ats["section_headings"]),
        ats_required_markers=tuple(ats["required_markers"]),
        ats_keyword_weight=float(ats["weights"]["keyword_coverage"]),
        ats_required_weight=float(ats["weights"]["required_coverage"]),
        search_focus_skill_to_keyword=search_focus["skill_to_keyword"],
        search_focus_domain_to_keyword=search_focus["domain_to_keyword"],
        search_focus_default_title=search_focus["default_title"],
        search_focus_titles_by_skill=search_focus.get("titles_by_skill", {}),
        search_focus_titles_by_domain=search_focus.get("titles_by_domain", {}),
        search_focus_stretch_roles=tuple(search_focus.get("stretch_roles_to_treat_cautiously", [])),
        fallback_resume_title=data["fallback_resume_title"],
    )


def resolve_config_path(path: str | Path | None = None) -> Path | None:
    if path is None:
        raw_path = os.getenv(CONFIG_PATH_ENVVAR)
        if not raw_path:
            return None
        path = raw_path
    return Path(path).expanduser().resolve()


def load_config(path: str | Path | None = None) -> Config:
    try:
        base = json.loads(DEFAULTS_PATH.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigError(f"Could not read bundled OfferQuest defaults from {DEFAULTS_PATH}.") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Bundled OfferQuest defaults in {DEFAULTS_PATH} are invalid JSON.") from exc

    config_path = resolve_config_path(path)
    if config_path is not None:
        try:
            overlay = json.loads(config_path.read_text(encoding="utf-8"))
        except OSError as exc:
            raise ConfigError(f"Could not read OfferQuest config file: {config_path}") from exc
        except json.JSONDecodeError as exc:
            raise ConfigError(f"OfferQuest config file is invalid JSON: {config_path}") from exc
        base = _deep_merge(base, overlay)

    try:
        return _config_from_dict(base)
    except (KeyError, TypeError, ValueError) as exc:
        source = str(config_path) if config_path is not None else str(DEFAULTS_PATH)
        raise ConfigError(f"OfferQuest config is missing or mis-typing required fields: {source}") from exc


_active: Config | None = None


def active() -> Config:
    global _active
    if _active is None:
        _active = load_config()
    return _active


def set_active(config: Config) -> None:
    global _active
    _active = config


def reset_to_defaults() -> None:
    global _active
    _active = None
