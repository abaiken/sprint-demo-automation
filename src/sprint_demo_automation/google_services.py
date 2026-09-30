from __future__ import annotations

from googleapiclient.discovery import build

from .config import AppConfig
from .google_auth import load_google_credentials

DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive"]
SLIDES_SCOPES = ["https://www.googleapis.com/auth/presentations"]
CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]


def build_drive_service(config: AppConfig):
    creds = load_google_credentials(
        scopes=sorted(set(DRIVE_SCOPES + CALENDAR_SCOPES + SLIDES_SCOPES)),
        credentials_path=config.google_credentials_path,
        token_path=config.google_token_path,
    )
    return build("drive", "v3", credentials=creds)


def build_slides_service(config: AppConfig):
    creds = load_google_credentials(
        scopes=sorted(set(DRIVE_SCOPES + SLIDES_SCOPES + CALENDAR_SCOPES)),
        credentials_path=config.google_credentials_path,
        token_path=config.google_token_path,
    )
    return build("slides", "v1", credentials=creds)
