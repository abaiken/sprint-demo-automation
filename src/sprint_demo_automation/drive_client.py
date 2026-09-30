from __future__ import annotations

import re

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
            orderBy="modifiedTime desc",
            pageSize=20,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        )
        .execute()
    )
    files = result.get("files", [])
    if not files:
        raise RuntimeError(f"No Google Slides presentations found in folder {folder_id}")

    for file_metadata in files:
        if looks_like_generated_copy(file_metadata.get("name", "")):
            return file_metadata

    return files[0]


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


def looks_like_generated_copy(name: str) -> bool:
    normalized = (name or "").strip()
    if not normalized:
        return False
    return bool(re.match(r"^Copy of\b", normalized, flags=re.I))
