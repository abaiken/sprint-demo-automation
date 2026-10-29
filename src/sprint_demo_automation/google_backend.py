"""Google API transport backends.

The coordinator logic should not care whether Google is reached through the
official Python client libraries or through the `gws` CLI. This module keeps
that choice in one place. All payloads (Slides batchUpdate requests, Drive
file bodies, ...) stay identical between backends because both speak the same
REST schema.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any, Protocol

from .config import AppConfig

GWS_INSTALL_HINT = (
    "The gws CLI is not installed. Install it with `brew install "
    "googleworkspace-cli`, `npm install -g @googleworkspace/cli`, or a release "
    "binary from https://github.com/googleworkspace/cli, then run "
    "`gws auth login -s drive,slides,calendar,sheets`. Alternatively set "
    "SPRINT_DEMO_GOOGLE_BACKEND=api and configure Google OAuth credentials."
)

GWS_EXIT_CODES = {
    1: "Google API error",
    2: "authentication error (run `gws auth login`)",
    3: "validation error",
    4: "discovery error (check network access)",
    5: "internal error",
}


class GoogleBackend(Protocol):
    def list_calendar_events(
        self,
        *,
        calendar_id: str,
        time_min: str,
        time_max: str,
        query: str,
        max_results: int,
    ) -> list[dict]: ...

    def list_drive_files(
        self,
        *,
        query: str,
        fields: str,
        order_by: str = "",
        page_size: int = 50,
    ) -> list[dict]: ...

    def get_drive_file(self, *, file_id: str, fields: str) -> dict: ...

    def copy_drive_file(self, *, file_id: str, body: dict, fields: str) -> dict: ...

    def delete_drive_file(self, file_id: str) -> None: ...

    def get_presentation(self, presentation_id: str) -> dict: ...

    def batch_update_presentation(
        self, *, presentation_id: str, requests: list[dict]
    ) -> dict: ...

    def get_sheet_metadata(self, *, spreadsheet_id: str, fields: str) -> dict: ...

    def get_sheet_values(self, *, spreadsheet_id: str, cell_range: str) -> dict: ...


def get_backend(config: AppConfig) -> GoogleBackend:
    name = (config.google_backend or "auto").strip().lower()
    if name == "auto":
        name = _auto_backend_name(config)
    if name == "gws":
        return GwsBackend(binary=shutil.which("gws") or "gws")
    if name == "api":
        return ApiBackend(config)
    raise RuntimeError(
        f"Unknown google_backend {config.google_backend!r}. "
        "Use 'auto', 'api', or 'gws'."
    )


def _auto_backend_name(config: AppConfig) -> str:
    """Prefer the Python API client when it has credentials to work with.

    Falling back to gws only when no OAuth files exist keeps existing setups
    unchanged while removing the credentials.json requirement for gws users.
    """
    if Path(config.google_credentials_path).exists():
        return "api"
    if Path(config.google_token_path).exists():
        return "api"
    if shutil.which("gws"):
        return "gws"
    return "api"


class ApiBackend:
    """Google APIs through the official Python client libraries."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def _service(self, name: str, version: str):
        try:
            from .google_services import build_service
        except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "The Google API Python client is not installed. Install it with "
                "`pip install -e \".[api]\"` or set "
                "SPRINT_DEMO_GOOGLE_BACKEND=gws."
            ) from exc
        return build_service(self.config, name, version)

    def list_calendar_events(
        self,
        *,
        calendar_id: str,
        time_min: str,
        time_max: str,
        query: str,
        max_results: int,
    ) -> list[dict]:
        result = (
            self._service("calendar", "v3")
            .events()
            .list(
                calendarId=calendar_id,
                timeMin=time_min,
                timeMax=time_max,
                q=query,
                singleEvents=True,
                orderBy="startTime",
                maxResults=max_results,
            )
            .execute()
        )
        return result.get("items", [])

    def list_drive_files(
        self,
        *,
        query: str,
        fields: str,
        order_by: str = "",
        page_size: int = 50,
    ) -> list[dict]:
        kwargs: dict[str, Any] = {
            "q": query,
            "fields": fields,
            "pageSize": page_size,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if order_by:
            kwargs["orderBy"] = order_by
        result = self._service("drive", "v3").files().list(**kwargs).execute()
        return result.get("files", [])

    def get_drive_file(self, *, file_id: str, fields: str) -> dict:
        return (
            self._service("drive", "v3")
            .files()
            .get(fileId=file_id, fields=fields, supportsAllDrives=True)
            .execute()
        )

    def copy_drive_file(self, *, file_id: str, body: dict, fields: str) -> dict:
        return (
            self._service("drive", "v3")
            .files()
            .copy(
                fileId=file_id,
                body=body,
                fields=fields,
                supportsAllDrives=True,
            )
            .execute()
        )

    def delete_drive_file(self, file_id: str) -> None:
        (
            self._service("drive", "v3")
            .files()
            .delete(fileId=file_id, supportsAllDrives=True)
            .execute()
        )

    def get_presentation(self, presentation_id: str) -> dict:
        return (
            self._service("slides", "v1")
            .presentations()
            .get(presentationId=presentation_id)
            .execute()
        )

    def batch_update_presentation(
        self, *, presentation_id: str, requests: list[dict]
    ) -> dict:
        return (
            self._service("slides", "v1")
            .presentations()
            .batchUpdate(
                presentationId=presentation_id,
                body={"requests": requests},
            )
            .execute()
        )

    def get_sheet_metadata(self, *, spreadsheet_id: str, fields: str) -> dict:
        return (
            self._service("sheets", "v4")
            .spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields=fields)
            .execute()
        )

    def get_sheet_values(self, *, spreadsheet_id: str, cell_range: str) -> dict:
        return (
            self._service("sheets", "v4")
            .spreadsheets()
            .values()
            .get(spreadsheetId=spreadsheet_id, range=cell_range)
            .execute()
        )


class GwsBackend:
    """Google APIs through the `gws` CLI (googleworkspace/cli)."""

    def __init__(self, binary: str = "gws") -> None:
        self.binary = binary

    def _run(self, *args: str, params: dict | None = None, body: dict | None = None) -> dict:
        command = [self.binary, *args]
        if params is not None:
            command += ["--params", json.dumps(params)]
        if body is not None:
            command += ["--json", json.dumps(body)]

        try:
            completed = subprocess.run(command, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise RuntimeError(GWS_INSTALL_HINT) from exc

        if completed.returncode != 0:
            reason = GWS_EXIT_CODES.get(completed.returncode, "unexpected error")
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(
                f"gws {' '.join(args)} failed ({reason}, exit "
                f"{completed.returncode}): {detail or 'no output'}"
            )

        output = (completed.stdout or "").strip()
        if not output:
            return {}
        try:
            return json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                f"gws {' '.join(args)} returned non-JSON output: {output[:500]}"
            ) from exc

    def list_calendar_events(
        self,
        *,
        calendar_id: str,
        time_min: str,
        time_max: str,
        query: str,
        max_results: int,
    ) -> list[dict]:
        result = self._run(
            "calendar",
            "events",
            "list",
            params={
                "calendarId": calendar_id,
                "timeMin": time_min,
                "timeMax": time_max,
                "q": query,
                "singleEvents": True,
                "orderBy": "startTime",
                "maxResults": max_results,
            },
        )
        return result.get("items", [])

    def list_drive_files(
        self,
        *,
        query: str,
        fields: str,
        order_by: str = "",
        page_size: int = 50,
    ) -> list[dict]:
        params: dict[str, Any] = {
            "q": query,
            "fields": fields,
            "pageSize": page_size,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if order_by:
            params["orderBy"] = order_by
        result = self._run("drive", "files", "list", params=params)
        return result.get("files", [])

    def get_drive_file(self, *, file_id: str, fields: str) -> dict:
        return self._run(
            "drive",
            "files",
            "get",
            params={"fileId": file_id, "fields": fields, "supportsAllDrives": True},
        )

    def copy_drive_file(self, *, file_id: str, body: dict, fields: str) -> dict:
        return self._run(
            "drive",
            "files",
            "copy",
            params={"fileId": file_id, "fields": fields, "supportsAllDrives": True},
            body=body,
        )

    def delete_drive_file(self, file_id: str) -> None:
        self._run(
            "drive",
            "files",
            "delete",
            params={"fileId": file_id, "supportsAllDrives": True},
        )

    def get_presentation(self, presentation_id: str) -> dict:
        return self._run(
            "slides",
            "presentations",
            "get",
            params={"presentationId": presentation_id},
        )

    def batch_update_presentation(
        self, *, presentation_id: str, requests: list[dict]
    ) -> dict:
        return self._run(
            "slides",
            "presentations",
            "batchUpdate",
            params={"presentationId": presentation_id},
            body={"requests": requests},
        )

    def get_sheet_metadata(self, *, spreadsheet_id: str, fields: str) -> dict:
        return self._run(
            "sheets",
            "spreadsheets",
            "get",
            params={"spreadsheetId": spreadsheet_id, "fields": fields},
        )

    def get_sheet_values(self, *, spreadsheet_id: str, cell_range: str) -> dict:
        return self._run(
            "sheets",
            "spreadsheets",
            "values",
            "get",
            params={"spreadsheetId": spreadsheet_id, "range": cell_range},
        )
