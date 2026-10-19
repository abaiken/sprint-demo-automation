from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

try:
    import tomllib  # type: ignore[attr-defined]
except ModuleNotFoundError:  # pragma: no cover - Python < 3.11
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ModuleNotFoundError:  # pragma: no cover - optional before install
        tomllib = None  # type: ignore[assignment]


@dataclass
class AppConfig:
    timezone: str = "America/New_York"
    next_demo_event_title: str = ""
    calendar_id: str = "primary"
    calendar_search_window_days: int = 90
    next_deck_date_offset_days: int = 14
    ceremony_lookahead_days: int = 21
    source_drive_folder_id: str = ""
    source_drive_folder_url: str = ""
    source_presentation_id: str = ""
    source_presentation_url: str = ""
    destination_drive_folder_id: str = ""
    destination_drive_folder_url: str = ""
    default_hire_dates_csv: str = ""
    hire_dates_sheet_id: str = ""
    hire_dates_sheet_url: str = ""
    hire_dates_sheet_range: str = ""
    new_deck_name_template: str = "Sprint Demo - {{nextDate}}"
    lead_reminder_template: str = (
        "Leads: please fill out your sprint demo slides for {{deckName}}: {{deckUrl}}"
    )
    rotate_team_order_for_next_sprint: bool = True
    slack_channel: str = "#team-demo"
    team_order: list[str] = field(default_factory=list)
    google_credentials_path: str = "credentials.json"
    google_token_path: str = "google_token.json"


def load_config(config_path: str | None = None) -> AppConfig:
    load_dotenv()

    resolved_path = Path(
        config_path
        or os.environ.get("SPRINT_DEMO_CONFIG_PATH")
        or "config.toml"
    )

    raw: dict = {}
    if resolved_path.exists():
        if tomllib is None:
            raw = _load_simple_toml(resolved_path)
        else:
            with resolved_path.open("rb") as handle:
                raw = tomllib.load(handle)

    return AppConfig(
        timezone=_env_or_raw("SPRINT_DEMO_TIMEZONE", raw, "timezone", "America/New_York"),
        next_demo_event_title=_env_or_raw(
            "SPRINT_DEMO_NEXT_DEMO_EVENT_TITLE", raw, "next_demo_event_title", ""
        ),
        calendar_id=_env_or_raw("SPRINT_DEMO_CALENDAR_ID", raw, "calendar_id", "primary"),
        calendar_search_window_days=int(
            _env_or_raw(
                "SPRINT_DEMO_CALENDAR_SEARCH_WINDOW_DAYS",
                raw,
                "calendar_search_window_days",
                90,
            )
        ),
        next_deck_date_offset_days=int(
            _env_or_raw(
                "SPRINT_DEMO_NEXT_DECK_DATE_OFFSET_DAYS",
                raw,
                "next_deck_date_offset_days",
                14,
            )
        ),
        ceremony_lookahead_days=int(
            _env_or_raw(
                "SPRINT_DEMO_CEREMONY_LOOKAHEAD_DAYS",
                raw,
                "ceremony_lookahead_days",
                21,
            )
        ),
        source_drive_folder_id=_env_or_raw(
            "SPRINT_DEMO_SOURCE_DRIVE_FOLDER_ID",
            raw,
            "source_drive_folder_id",
            "",
        ),
        source_drive_folder_url=_env_or_raw(
            "SPRINT_DEMO_SOURCE_DRIVE_FOLDER_URL",
            raw,
            "source_drive_folder_url",
            "",
        ),
        source_presentation_id=_env_or_raw(
            "SPRINT_DEMO_SOURCE_PRESENTATION_ID",
            raw,
            "source_presentation_id",
            "",
        ),
        source_presentation_url=_env_or_raw(
            "SPRINT_DEMO_SOURCE_PRESENTATION_URL",
            raw,
            "source_presentation_url",
            "",
        ),
        destination_drive_folder_id=_env_or_raw(
            "SPRINT_DEMO_DESTINATION_DRIVE_FOLDER_ID",
            raw,
            "destination_drive_folder_id",
            "",
        ),
        destination_drive_folder_url=_env_or_raw(
            "SPRINT_DEMO_DESTINATION_DRIVE_FOLDER_URL",
            raw,
            "destination_drive_folder_url",
            "",
        ),
        default_hire_dates_csv=_env_or_raw(
            "SPRINT_DEMO_DEFAULT_HIRE_DATES_CSV",
            raw,
            "default_hire_dates_csv",
            "",
        ),
        hire_dates_sheet_id=_env_or_raw(
            "SPRINT_DEMO_HIRE_DATES_SHEET_ID",
            raw,
            "hire_dates_sheet_id",
            "",
        ),
        hire_dates_sheet_url=_env_or_raw(
            "SPRINT_DEMO_HIRE_DATES_SHEET_URL",
            raw,
            "hire_dates_sheet_url",
            "",
        ),
        hire_dates_sheet_range=_env_or_raw(
            "SPRINT_DEMO_HIRE_DATES_SHEET_RANGE",
            raw,
            "hire_dates_sheet_range",
            "",
        ),
        new_deck_name_template=_env_or_raw(
            "SPRINT_DEMO_NEW_DECK_NAME_TEMPLATE",
            raw,
            "new_deck_name_template",
            "Sprint Demo - {{nextDate}}",
        ),
        lead_reminder_template=_env_or_raw(
            "SPRINT_DEMO_LEAD_REMINDER_TEMPLATE",
            raw,
            "lead_reminder_template",
            "Leads: please fill out your sprint demo slides for {{deckName}}: {{deckUrl}}",
        ),
        rotate_team_order_for_next_sprint=_parse_bool(
            _env_or_raw(
                "SPRINT_DEMO_ROTATE_TEAM_ORDER",
                raw,
                "rotate_team_order_for_next_sprint",
                True,
            )
        ),
        slack_channel=_env_or_raw(
            "SPRINT_DEMO_SLACK_CHANNEL",
            raw,
            "slack_channel",
            "#team-demo",
        ),
        team_order=list(raw.get("team_order", [])),
        google_credentials_path=_env_or_raw(
            "SPRINT_DEMO_GOOGLE_CREDENTIALS_PATH",
            raw,
            "google_credentials_path",
            "credentials.json",
        ),
        google_token_path=_env_or_raw(
            "SPRINT_DEMO_GOOGLE_TOKEN_PATH",
            raw,
            "google_token_path",
            "google_token.json",
        ),
    )


def _env_or_raw(env_key: str, raw: dict, raw_key: str, default):
    return os.environ.get(env_key, raw.get(raw_key, default))


def _parse_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "n"}


def _load_simple_toml(path: Path) -> dict:
    """
    Lightweight parser for the small flat config.toml we ship with this project.
    This is only used before dependencies are installed on Python < 3.11.
    """
    result: dict = {}
    current_list_key: str | None = None
    current_list: list[str] = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if current_list_key:
            if line == "]":
                result[current_list_key] = current_list
                current_list_key = None
                current_list = []
                continue
            current_list.append(line.rstrip(",").strip().strip('"').strip("'"))
            continue

        if "=" not in line:
            continue

        key, value = [part.strip() for part in line.split("=", 1)]

        if value == "[":
            current_list_key = key
            current_list = []
            continue

        result[key] = _parse_simple_toml_value(value)

    return result


def _parse_simple_toml_value(value: str):
    value = value.strip()
    if value.startswith('"') and value.endswith('"'):
        return value[1:-1]
    if value.startswith("'") and value.endswith("'"):
        return value[1:-1]
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return int(value)
    except ValueError:
        return value
