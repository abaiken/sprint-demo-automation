from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import AppConfig
from .csv_support import get_named_value, read_csv_records
from .messages import (
    build_coordinator_summary_message,
    build_mc_request_message,
    build_walkout_interest_message,
)


@dataclass
class Anniversary:
    name: str
    hire_date: str
    anniversary_date: str
    years: int


@dataclass
class WalkoutCandidate:
    name: str
    email: str
    team: str
    hire_date: str
    walkout_status: str = ""
    last_walkout_date: str = ""


def build_dry_run_plan(config: AppConfig, hire_dates_csv: str) -> dict:
    from .calendar_client import compute_next_demo_date
    from .drive_client import resolve_source_presentation

    next_demo_date = compute_next_demo_date(config)
    records = read_csv_records(hire_dates_csv)
    anniversaries = find_upcoming_anniversaries(
        records, next_demo_date, config.ceremony_lookahead_days, config.timezone
    )
    walkout_candidates = select_walkout_candidates(records)
    source_presentation = None
    if (
        config.source_presentation_id
        or config.source_presentation_url
        or config.source_drive_folder_id
        or config.source_drive_folder_url
    ):
        try:
            source_presentation = resolve_source_presentation(config)
        except Exception as error:  # pragma: no cover - live integration fallback
            source_presentation = {"error": str(error)}
    rotated_team_order = rotate_team_order(
        config.team_order, config.rotate_team_order_for_next_sprint
    )
    deck_name = config.new_deck_name_template.replace(
        "{{nextDate}}", format_date(next_demo_date)
    )
    top_walkout_candidate = walkout_candidates[0] if walkout_candidates else None

    return {
        "generated_at": datetime.now(ZoneInfo(config.timezone)).isoformat(),
        "next_demo_date": format_date(next_demo_date),
        "proposed_deck_name": deck_name,
        "source_presentation": source_presentation,
        "current_team_order": config.team_order,
        "proposed_team_order": rotated_team_order,
        "lead_reminder_message": build_lead_reminder_message(
            config,
            deck_name=deck_name,
            deck_url="https://docs.google.com/presentation/d/NEW_DECK_ID/edit",
        ),
        "coordinator_summary_message": build_coordinator_summary_message(
            config,
            deck_name=deck_name,
            deck_url="https://docs.google.com/presentation/d/NEW_DECK_ID/edit",
            anniversary_count=len(anniversaries),
            walkout_candidate_name=top_walkout_candidate.name if top_walkout_candidate else None,
        ),
        "slack_channel": config.slack_channel,
        "anniversary_count": len(anniversaries),
        "anniversaries": [asdict(item) for item in anniversaries],
        "walkout_candidate_count": len(walkout_candidates),
        "walkout_candidates": [asdict(item) for item in walkout_candidates],
    }


def find_upcoming_anniversaries(
    records: list[dict[str, str]],
    next_demo_date: datetime,
    lookahead_days: int,
    timezone: str,
) -> list[Anniversary]:
    today = datetime.now(ZoneInfo(timezone)).date()
    window_end = next_demo_date.date() + timedelta(days=lookahead_days)
    items: list[Anniversary] = []

    for row in records:
        candidate = build_anniversary_candidate(row, today, window_end)
        if candidate:
            items.append(candidate)

    return sorted(items, key=lambda item: item.anniversary_date)


def build_anniversary_candidate(
    row: dict[str, str],
    today,
    window_end,
) -> Anniversary | None:
    name = get_named_value(row, "name", "associate", "employee")
    hire_date_raw = get_named_value(row, "hire date", "start date", "anniversary date")
    hire_date = parse_date(hire_date_raw)

    if not name or hire_date is None:
        return None

    anniversary = hire_date.replace(year=today.year).date()
    if anniversary < today:
        anniversary = hire_date.replace(year=today.year + 1).date()

    if anniversary > window_end:
        return None

    return Anniversary(
        name=name,
        hire_date=hire_date.date().isoformat(),
        anniversary_date=anniversary.isoformat(),
        years=anniversary.year - hire_date.year,
    )


def select_walkout_candidates(records: list[dict[str, str]]) -> list[WalkoutCandidate]:
    candidates: list[WalkoutCandidate] = []
    for row in records:
        name = get_named_value(row, "name", "associate", "employee")
        eligible_value = get_named_value(row, "eligible", "walkout eligible").lower()
        walkout_status = get_named_value(row, "walkout")

        if not name:
            continue
        if eligible_value in {"no", "false", "n", "ineligible"}:
            continue
        if walkout_status.strip().lower() == "opt-out":
            continue

        candidates.append(
            WalkoutCandidate(
                name=name,
                email=get_named_value(row, "email", "email address"),
                team=get_named_value(row, "team", "org", "organization"),
                hire_date=get_named_value(row, "hire date", "start date"),
                walkout_status=walkout_status.strip(),
                last_walkout_date=get_named_value(
                    row,
                    "last walkout date",
                    "walkout date",
                ),
            )
        )

    return candidates


def choose_walkout_candidate(
    records: list[dict[str, str]],
) -> tuple[WalkoutCandidate | None, str | None]:
    candidates = select_walkout_candidates(records)
    if not candidates:
        return None, None

    blank_walkout_candidates = [
        candidate for candidate in candidates if not candidate.walkout_status.strip()
    ]
    candidate_pool = blank_walkout_candidates or candidates
    candidate, reason = choose_walkout_candidate_from_pool(candidate_pool)

    if candidate is None:
        return None, None

    if blank_walkout_candidates:
        if reason:
            return candidate, f"blank walkout column, {reason}"
        return candidate, "blank walkout column"

    return candidate, reason


def choose_walkout_candidate_from_pool(
    candidates: list[WalkoutCandidate],
) -> tuple[WalkoutCandidate | None, str | None]:
    if not candidates:
        return None, None

    never_selected: list[WalkoutCandidate] = []
    dated_candidates: list[tuple[datetime, WalkoutCandidate]] = []
    undated_candidates: list[WalkoutCandidate] = []

    for candidate in candidates:
        parsed_last_walkout = parse_walkout_date(candidate.last_walkout_date)
        if not candidate.last_walkout_date.strip():
            never_selected.append(candidate)
            continue
        if parsed_last_walkout is not None:
            dated_candidates.append((parsed_last_walkout, candidate))
            continue
        undated_candidates.append(candidate)

    if never_selected:
        never_selected.sort(
            key=lambda item: (
                parse_date(item.hire_date) or datetime.max,
                item.name.lower(),
            )
        )
        return never_selected[0], "no recorded prior walk-out"

    if dated_candidates:
        dated_candidates.sort(key=lambda item: (item[0], item[1].name.lower()))
        return dated_candidates[0][1], "oldest recorded walk-out"

    undated_candidates.sort(key=lambda item: item.name.lower())
    return undated_candidates[0], "walk-out history needs manual review"


def build_create_deck_todo(
    config: AppConfig,
    *,
    next_demo_date: datetime,
    deck_name: str,
    deck_url: str,
    source_presentation_id: str,
) -> str:
    hire_dates_available = bool(
        config.default_hire_dates_csv and Path(config.default_hire_dates_csv).exists()
    )
    anniversaries = (
        load_create_deck_anniversaries(config, source_presentation_id, next_demo_date)
        if hire_dates_available
        else []
    )
    records = read_csv_records(config.default_hire_dates_csv) if hire_dates_available else []
    walkout_candidate, walkout_reason = choose_walkout_candidate(records)

    if hire_dates_available:
        anniversary_lines = (
            [f"- {item.name} ({item.years} years on {item.anniversary_date})" for item in anniversaries]
            if anniversaries
            else ["- No anniversaries found for this demo window"]
        )
    else:
        anniversary_lines = [
            "- Skipped: no hire-dates CSV configured locally"
        ]

    walkout_section = ["- Skipped: no hire-dates CSV configured locally"]
    if hire_dates_available and walkout_candidate:
        walkout_section = [
            f"- {walkout_candidate.name}"
            + (f" [{walkout_candidate.email}]" if walkout_candidate.email else "")
            + (f" - {walkout_reason}" if walkout_reason else ""),
            build_walkout_interest_message(walkout_candidate.name, walkout_reason),
        ]
    elif hire_dates_available:
        walkout_section = ["- No walkout candidate found"]

    parts = [
        f"Deck ready: {deck_name}",
        deck_url,
        "",
        "TODO for ceremonies coordinator",
        "",
        "1. Work anniversaries to find photos for",
        *anniversary_lines,
        "",
        "2. Slack message for the channel",
        build_lead_reminder_message(config, deck_name=deck_name, deck_url=deck_url),
        "",
        "3. Most likely walkout song candidate",
        *walkout_section,
        "",
        "4. Message to the MCs",
        build_mc_request_message(deck_url),
    ]
    return "\n".join(parts)


def load_create_deck_anniversaries(
    config: AppConfig,
    source_presentation_id: str,
    next_demo_date: datetime,
) -> list[Anniversary]:
    from .google_services import build_slides_service
    from .slides_client import load_upcoming_anniversaries

    if not config.default_hire_dates_csv:
        return []

    slides_service = build_slides_service(config)
    presentation = (
        slides_service.presentations().get(presentationId=source_presentation_id).execute()
    )
    return load_upcoming_anniversaries(config, presentation, next_demo_date)


def rotate_team_order(team_order: list[str], should_rotate: bool) -> list[str]:
    if not should_rotate or len(team_order) < 2:
        return list(team_order)
    return [team_order[-1], *team_order[:-1]]


def build_lead_reminder_message(
    config: AppConfig, *, deck_name: str, deck_url: str
) -> str:
    return (
        config.lead_reminder_template.replace("{{deckName}}", deck_name).replace(
            "{{deckUrl}}", deck_url
        )
    )


def format_date(value: datetime) -> str:
    return value.date().isoformat()


def parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def parse_walkout_date(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None

    normalized = raw.replace("sept ", "sep ").replace("Sept ", "Sep ")
    formats = [
        "%b %d %Y",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%d-%b-%y",
        "%d-%B-%y",
        "%m/%d/%Y",
        "%m/%d/%y",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%d-%b-%y",
        "%d-%B-%y",
        "%d-%m-%Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(normalized, fmt)
        except ValueError:
            continue

    date_match = None
    import re

    patterns = [
        r"(\d{1,2}/\d{1,2}/\d{2,4})",
        r"([A-Za-z]{3,9}\s+\d{1,2}\s+\d{2,4})",
        r"(\d{1,2}-[A-Za-z]{3,9}-\d{2,4})",
    ]
    for pattern in patterns:
        date_match = re.search(pattern, normalized)
        if date_match:
            break
    if not date_match:
        return None

    extracted = date_match.group(1)
    for fmt in formats:
        try:
            return datetime.strptime(extracted, fmt)
        except ValueError:
            continue
    return None
