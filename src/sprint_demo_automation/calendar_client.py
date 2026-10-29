from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import AppConfig
from .google_backend import get_backend
from .google_services import CALENDAR_SCOPES, DRIVE_SCOPES, SHEETS_SCOPES, SLIDES_SCOPES

ALL_REQUIRED_SCOPES = sorted(
    set(CALENDAR_SCOPES + DRIVE_SCOPES + SLIDES_SCOPES + SHEETS_SCOPES)
)


def compute_next_demo_date(config: AppConfig) -> datetime:
    try:
        event_date = lookup_next_demo_date_from_calendar(config)
        if event_date is not None:
            return event_date
    except ModuleNotFoundError:
        pass
    except FileNotFoundError:
        pass
    except RuntimeError:
        pass

    now = datetime.now(ZoneInfo(config.timezone))
    return now + timedelta(days=config.next_deck_date_offset_days)


def lookup_next_demo_date_from_calendar(config: AppConfig) -> datetime | None:
    backend = get_backend(config)

    now = datetime.now(ZoneInfo(config.timezone))
    window_end = now + timedelta(days=config.calendar_search_window_days)

    search_queries = []
    if config.next_demo_event_title:
        search_queries.append(config.next_demo_event_title)
    search_queries.extend(["Sprint Demo", "Demo"])

    seen_event_ids: set[str] = set()
    candidate_events: list[dict] = []
    for query in search_queries:
        events = backend.list_calendar_events(
            calendar_id=config.calendar_id,
            time_min=now.isoformat(),
            time_max=window_end.isoformat(),
            query=query,
            max_results=25,
        )
        for event in events:
            event_id = str(event.get("id", ""))
            if event_id and event_id in seen_event_ids:
                continue
            if event_id:
                seen_event_ids.add(event_id)
            candidate_events.append(event)

    best_match = select_best_demo_event(candidate_events, config.next_demo_event_title)
    if best_match is not None:
        start = best_match.get("start", {})
        start_value = start.get("dateTime") or start.get("date")
        if start_value:
            parsed = datetime.fromisoformat(start_value.replace("Z", "+00:00"))
            return parsed.astimezone(ZoneInfo(config.timezone))

    raise RuntimeError(
        "No future calendar event matched the configured next_demo_event_title"
    )


def select_best_demo_event(
    events: list[dict], configured_title: str
) -> dict | None:
    normalized_configured_title = configured_title.lower().strip()
    prioritized: list[tuple[int, dict]] = []

    for event in events:
        title = str(event.get("summary", "")).lower().strip()
        if not title:
            continue

        score = 0
        if normalized_configured_title and normalized_configured_title in title:
            score += 100
        if "sprint demo" in title:
            score += 50
        if "hybrid cloud console" in title:
            score += 25
        if "demo" in title:
            score += 10

        if score <= 0:
            continue
        prioritized.append((score, event))

    if not prioritized:
        return None

    prioritized.sort(
        key=lambda item: (
            -item[0],
            (
                item[1].get("start", {}).get("dateTime")
                or item[1].get("start", {}).get("date")
                or ""
            ),
        )
    )
    return prioritized[0][1]
