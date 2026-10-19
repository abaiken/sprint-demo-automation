from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime

from .config import load_config
from .planner import (
    build_create_deck_todo,
    build_dry_run_plan,
    build_lead_reminder_message,
    format_date,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sprint-demo",
        description="Local Python tooling for sprint demo ceremony automation",
    )
    parser.add_argument(
        "--config",
        help="Path to config.toml. Defaults to SPRINT_DEMO_CONFIG_PATH or ./config.toml",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    dry_run = subparsers.add_parser(
        "dry-run", help="Build a local coordinator dry run from the configured hire-dates source"
    )
    dry_run.add_argument(
        "--hire-dates-csv",
        help="Optional CSV override. Defaults to the configured hire-dates source",
    )
    dry_run.add_argument(
        "--folder-id",
        help="Optional Google Drive folder ID or URL override used to resolve the latest presentation",
    )

    preview = subparsers.add_parser(
        "preview-lead-reminder", help="Preview the Slack reminder text"
    )
    preview.add_argument("--deck-name", required=True)
    preview.add_argument("--deck-url", required=True)

    resolve_source = subparsers.add_parser(
        "resolve-source-deck",
        help="Find the latest Google Slides presentation in a Drive folder",
    )
    resolve_source.add_argument(
        "--folder-id",
        help="Folder ID or URL to search. Defaults to source_drive_folder_id/source_drive_folder_url in config.toml",
    )

    lookup_photo = subparsers.add_parser(
        "lookup-slack-photo",
        help="Look up a Slack user's profile photo by email",
    )
    lookup_photo.add_argument("--email", required=True)

    create_deck = subparsers.add_parser(
        "create-deck",
        help="Copy the source Google Slides deck, update standard text, and reorder team sections",
    )
    create_deck.add_argument(
        "--folder-id",
        help="Optional Google Drive source folder ID or URL override used to find the latest presentation",
    )
    create_deck.add_argument(
        "--source-presentation-id",
        help="Optional explicit source presentation ID override",
    )
    create_deck.add_argument(
        "--source-presentation-url",
        help="Optional explicit source presentation URL override",
    )

    inspect_order = subparsers.add_parser(
        "inspect-team-order",
        help="Inspect how the script classifies team and non-team slides in a presentation",
    )
    inspect_order.add_argument(
        "--presentation-id",
        help="Optional explicit Google Slides presentation ID override",
    )
    inspect_order.add_argument(
        "--presentation-url",
        help="Optional explicit Google Slides presentation URL override",
    )

    subparsers.add_parser(
        "next-demo-date", help="Resolve the next demo date from calendar or fallback offset"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)

    if args.command == "dry-run":
        hire_dates_csv = args.hire_dates_csv or config.default_hire_dates_csv
        if not hire_dates_csv and not config.hire_dates_sheet_id and not config.hire_dates_sheet_url:
            parser.error(
                "dry-run requires --hire-dates-csv, SPRINT_DEMO_DEFAULT_HIRE_DATES_CSV, or a configured hire-dates Google Sheet"
            )
        if args.folder_id:
            config.source_drive_folder_id = args.folder_id
        result = build_dry_run_plan(config, hire_dates_csv)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "preview-lead-reminder":
        print(
            build_lead_reminder_message(
                config, deck_name=args.deck_name, deck_url=args.deck_url
            )
        )
        return 0

    if args.command == "resolve-source-deck":
        from .drive_client import resolve_source_presentation

        if args.folder_id:
            config.source_drive_folder_id = args.folder_id
        print(json.dumps(resolve_source_presentation(config), indent=2))
        return 0

    if args.command == "lookup-slack-photo":
        from .slack_client import lookup_slack_photo

        print(json.dumps(lookup_slack_photo(args.email), indent=2))
        return 0

    if args.command == "create-deck":
        from .calendar_client import compute_next_demo_date
        from .slides_client import create_next_sprint_deck

        if args.folder_id:
            config.source_drive_folder_id = args.folder_id
        if args.source_presentation_id:
            config.source_presentation_id = args.source_presentation_id
        if args.source_presentation_url:
            config.source_presentation_url = args.source_presentation_url

        next_demo_date = compute_next_demo_date(config)
        result = create_next_sprint_deck(config, next_demo_date)
        print(
            build_create_deck_todo(
                config,
                next_demo_date=datetime.fromisoformat(result["nextDemoDate"]),
                deck_name=result["copiedPresentation"]["name"],
                deck_url=result["copiedPresentation"]["webViewLink"],
                source_presentation_id=result["sourcePresentation"]["id"],
            )
        )
        return 0

    if args.command == "inspect-team-order":
        from .slides_client import inspect_presentation_team_order

        if args.presentation_id:
            config.source_presentation_id = args.presentation_id
        if args.presentation_url:
            config.source_presentation_url = args.presentation_url

        result = inspect_presentation_team_order(config)
        print(json.dumps(result, indent=2))
        return 0

    if args.command == "next-demo-date":
        from .calendar_client import compute_next_demo_date

        print(format_date(compute_next_demo_date(config)))
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
