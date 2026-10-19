from __future__ import annotations

import re
from datetime import datetime

from .config import AppConfig
from .google_ids import extract_google_file_id
from .google_services import build_drive_service

GOOGLE_SLIDES_MIME_TYPE = "application/vnd.google-apps.presentation"


def resolve_source_presentation(config: AppConfig, folder_id: str | None = None) -> dict:
    source_presentation_id = extract_google_file_id(config.source_presentation_id)
    if not source_presentation_id:
        source_presentation_id = extract_google_file_id(config.source_presentation_url)
    if source_presentation_id:
        return get_file_metadata(config, source_presentation_id)

    effective_folder_id = extract_google_file_id(folder_id or config.source_drive_folder_id)
    if not effective_folder_id:
        effective_folder_id = extract_google_file_id(config.source_drive_folder_url)
    if not effective_folder_id:
        raise RuntimeError(
            "No source presentation configured. Set source_presentation_id, "
            "source_presentation_url, source_drive_folder_id, or source_drive_folder_url."
        )

    return find_latest_presentation_in_folder(config, effective_folder_id)


def find_latest_presentation_in_folder(config: AppConfig, folder_id: str) -> dict:
    service = build_drive_service(config)
    result = (
        service.files()
        .list(
            q=(
                f"'{folder_id}' in parents and "
                f"mimeType='{GOOGLE_SLIDES_MIME_TYPE}' and trashed=false"
            ),
            fields="files(id,name,webViewLink,createdTime,modifiedTime,parents)",
            orderBy="createdTime desc",
            pageSize=50,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = result.get("files", [])
    if not files:
        raise RuntimeError(f"No Google Slides presentations found in folder {folder_id}")

    dated_files = []
    undated_files = []
    for file_metadata in files:
        deck_date = extract_deck_date(file_metadata.get("name", ""))
        created = parse_google_timestamp(file_metadata.get("createdTime", ""))
        modified = parse_google_timestamp(file_metadata.get("modifiedTime", ""))
        if deck_date is not None:
            dated_files.append((deck_date, created, modified, file_metadata))
        else:
            undated_files.append((created, modified, file_metadata))

    if dated_files:
        dated_files.sort(key=lambda item: (item[0], item[1] or datetime.min, item[2] or datetime.min), reverse=True)
        return dated_files[0][3]

    undated_files.sort(key=lambda item: (item[0] or datetime.min, item[1] or datetime.min), reverse=True)
    return undated_files[0][2]


def get_file_metadata(config: AppConfig, file_id: str) -> dict:
    service = build_drive_service(config)
    return (
        service.files()
        .get(
            fileId=file_id,
            fields="id,name,webViewLink,createdTime,modifiedTime,parents",
            supportsAllDrives=True,
        )
        .execute()
    )


def delete_file(config: AppConfig, file_id: str) -> None:
    service = build_drive_service(config)
    (
        service.files()
        .delete(
            fileId=file_id,
            supportsAllDrives=True,
        )
        .execute()
    )


def looks_like_generated_copy(name: str) -> bool:
    normalized = (name or "").strip()
    if not normalized:
        return False
    return bool(re.match(r"^Copy of\b", normalized, flags=re.I))


def extract_deck_date(name: str) -> datetime | None:
    match = re.search(r"_(\d{6})(?:\b|$)", (name or "").strip())
    if not match:
        return None
    try:
        return datetime.strptime(match.group(1), "%m%d%y")
    except ValueError:
        return None


def parse_google_timestamp(value: str) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None
