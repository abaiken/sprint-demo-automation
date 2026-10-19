from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from .config import AppConfig
from .csv_support import normalize_header, normalize_row, read_csv_records
from .google_ids import extract_google_file_id
from .google_services import build_sheets_service


def load_hire_date_records(
    config: AppConfig,
    *,
    csv_path_override: str = "",
    sheet_id_override: str = "",
    sheet_range_override: str = "",
) -> list[dict[str, str]]:
    sheet_id = extract_google_file_id(sheet_id_override) or extract_google_file_id(
        config.hire_dates_sheet_id
    ) or extract_google_file_id(config.hire_dates_sheet_url)
    if sheet_id:
        return read_google_sheet_records(
            config,
            spreadsheet_id=sheet_id,
            cell_range=sheet_range_override or config.hire_dates_sheet_range,
        )

    csv_path = csv_path_override or config.default_hire_dates_csv
    if csv_path:
        return read_csv_records(csv_path)

    return []


def hire_date_source_configured(
    config: AppConfig,
    *,
    csv_path_override: str = "",
    sheet_id_override: str = "",
) -> bool:
    if extract_google_file_id(sheet_id_override):
        return True
    if extract_google_file_id(config.hire_dates_sheet_id):
        return True
    if extract_google_file_id(config.hire_dates_sheet_url):
        return True
    return bool(csv_path_override or config.default_hire_dates_csv)


def extract_google_sheet_gid(value: str) -> str:
    parsed = urlparse((value or "").strip())
    if parsed.fragment.startswith("gid="):
        return parsed.fragment.split("=", 1)[1]
    query_gid = parse_qs(parsed.query).get("gid", [""])[0]
    return query_gid


def read_google_sheet_records(
    config: AppConfig,
    *,
    spreadsheet_id: str,
    cell_range: str = "",
) -> list[dict[str, str]]:
    service = build_sheets_service(config)

    resolved_range = cell_range.strip()
    if not resolved_range:
        metadata = (
            service.spreadsheets()
            .get(spreadsheetId=spreadsheet_id, fields="sheets(properties(title,sheetId))")
            .execute()
        )
        sheets = metadata.get("sheets", [])
        if not sheets:
            return []

        source_gid = extract_google_sheet_gid(config.hire_dates_sheet_url)
        chosen_sheet = sheets[0]
        if source_gid:
            for sheet in sheets:
                sheet_id = str(sheet.get("properties", {}).get("sheetId", ""))
                if sheet_id == source_gid:
                    chosen_sheet = sheet
                    break

        chosen_title = chosen_sheet.get("properties", {}).get("title", "").replace("'", "''")
        resolved_range = f"'{chosen_title}'!A:Z"

    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=spreadsheet_id, range=resolved_range)
        .execute()
    )
    values = result.get("values", [])
    if not values:
        return []

    headers = [normalize_header(item) for item in values[0]]
    records: list[dict[str, str]] = []
    for row_values in values[1:]:
        padded_values = list(row_values) + [""] * max(0, len(headers) - len(row_values))
        row = {
            headers[index]: str(padded_values[index] or "").strip()
            for index in range(len(headers))
            if headers[index]
        }
        records.append(normalize_row(row))

    return records
