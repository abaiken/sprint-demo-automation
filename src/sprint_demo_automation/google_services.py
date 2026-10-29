from __future__ import annotations

from .config import AppConfig

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
SLIDES_SCOPES = ["https://www.googleapis.com/auth/presentations"]
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
SHEETS_SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

ALL_SCOPES = sorted(
    set(DRIVE_SCOPES + CALENDAR_SCOPES + SLIDES_SCOPES + SHEETS_SCOPES)
)

# These helpers are only used by the "api" backend. Imports stay local so the
# package can be used with the gws CLI backend without the Google client
# libraries installed.
def build_service(config: AppConfig, service_name: str, version: str):
    from googleapiclient.discovery import build

    from .google_auth import load_google_credentials

    creds = load_google_credentials(
        scopes=ALL_SCOPES,
        credentials_path=config.google_credentials_path,
        token_path=config.google_token_path,
    )
    return build(service_name, version, credentials=creds)


def build_drive_service(config: AppConfig):
    return build_service(config, "drive", "v3")


def build_slides_service(config: AppConfig):
    return build_service(config, "slides", "v1")


def build_sheets_service(config: AppConfig):
    return build_service(config, "sheets", "v4")


def build_calendar_service(config: AppConfig):
    return build_service(config, "calendar", "v3")
