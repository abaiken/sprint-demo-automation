from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .config import AppConfig
from .deck_defaults import (
    FIXED_SLIDES_AT_END,
    FIXED_SLIDES_AT_START,
    GLOBAL_REPLACEMENTS,
    TEAM_CONFIGS,
    TeamConfig,
)
from .drive_client import get_file_metadata
from .google_ids import extract_google_file_id
from .google_services import build_drive_service, build_slides_service


@dataclass(frozen=True)
class SlideBlock:
    slide_ids: list[str]
    team_key: str | None = None
    block_kind: str = "anchored"
    is_skipped: bool = False


@dataclass(frozen=True)
class ShapeLine:
    text: str
    start: int
    end: int
    is_bold: bool
    word_count: int


def create_next_sprint_deck(config: AppConfig, next_demo_date: datetime) -> dict:
    source = resolve_source_deck_for_copy(config)
    new_name = build_new_file_name(source["name"], next_demo_date)
    copied = copy_presentation(
        config,
        source_presentation_id=source["id"],
        new_name=new_name,
        destination_folder_id=config.destination_drive_folder_id or None,
        source_parent_ids=source.get("parents") or [],
    )
    update_result = apply_standard_updates(
        config,
        copied["id"],
        next_demo_date,
    )
    return {
        "nextDemoDate": next_demo_date.date().isoformat(),
        "sourcePresentation": source,
        "copiedPresentation": copied,
        "slideUpdates": update_result,
    }


def inspect_presentation_team_order(config: AppConfig) -> dict:
    source = resolve_source_deck_for_copy(config)
    slides_service = build_slides_service(config)
    presentation = (
        slides_service.presentations().get(presentationId=source["id"]).execute()
    )
    return {
        "sourcePresentation": source,
        "configuredTeamOrder": config.team_order,
        "diagnostics": build_reorder_diagnostics(
            presentation, config.rotate_team_order_for_next_sprint
        ),
    }


def resolve_source_deck_for_copy(config: AppConfig) -> dict:
    source_presentation_id = extract_google_file_id(config.source_presentation_id)
    if not source_presentation_id:
        source_presentation_id = extract_google_file_id(config.source_presentation_url)
    if source_presentation_id:
        return get_file_metadata(config, source_presentation_id)

    from .drive_client import resolve_source_presentation

    return resolve_source_presentation(config)


def copy_presentation(
    config: AppConfig,
    *,
    source_presentation_id: str,
    new_name: str,
    destination_folder_id: str | None,
    source_parent_ids: list[str],
) -> dict:
    service = build_drive_service(config)
    body = {"name": new_name}
    parsed_destination_folder_id = extract_google_file_id(destination_folder_id or "")
    if not parsed_destination_folder_id:
        parsed_destination_folder_id = extract_google_file_id(
            config.destination_drive_folder_id
        )
    if not parsed_destination_folder_id:
        parsed_destination_folder_id = extract_google_file_id(
            config.destination_drive_folder_url
        )

    if parsed_destination_folder_id:
        body["parents"] = [parsed_destination_folder_id]
    elif source_parent_ids:
        body["parents"] = source_parent_ids

    return (
        service.files()
        .copy(
            fileId=source_presentation_id,
            body=body,
            fields="id,name,webViewLink,parents,createdTime,modifiedTime",
            supportsAllDrives=True,
        )
        .execute()
    )


def apply_standard_updates(
    config: AppConfig,
    presentation_id: str,
    next_demo_date: datetime,
) -> dict:
    slides_service = build_slides_service(config)
    presentation = (
        slides_service.presentations().get(presentationId=presentation_id).execute()
    )
    diagnostics = build_reorder_diagnostics(
        presentation, config.rotate_team_order_for_next_sprint
    )
    requests = build_update_requests(
        config=config,
        presentation=presentation,
        next_demo_date=next_demo_date,
        should_rotate=config.rotate_team_order_for_next_sprint,
    )
    if not requests:
        return {"updated": False, "requestCount": 0, "diagnostics": diagnostics}

    slides_service.presentations().batchUpdate(
        presentationId=presentation_id,
        body={"requests": requests},
    ).execute()
    return {"updated": True, "requestCount": len(requests), "diagnostics": diagnostics}


def build_update_requests(
    *,
    config: AppConfig,
    presentation: dict,
    next_demo_date: datetime,
    should_rotate: bool,
) -> list[dict]:
    requests: list[dict] = []

    cover_range_text, previous_end_text = parse_cover_range(presentation)
    if cover_range_text and previous_end_text:
        requests.append(
            {
                "replaceAllText": {
                    "containsText": {"text": cover_range_text, "matchCase": True},
                    "replaceText": format_cover_range(previous_end_text, next_demo_date),
                }
            }
        )

    for old, new in GLOBAL_REPLACEMENTS:
        requests.append(
            {
                "replaceAllText": {
                    "containsText": {"text": old, "matchCase": True},
                    "replaceText": new,
                }
            }
        )

    insertion_index = FIXED_SLIDES_AT_START
    for block in build_ordered_slide_blocks(presentation, should_rotate):
        requests.append(
            {
                "updateSlidesPosition": {
                    "slideObjectIds": block,
                    "insertionIndex": insertion_index,
                }
            }
        )
        insertion_index += len(block)

    requests.extend(build_team_slide_body_cleanup_requests(presentation))
    requests.extend(build_demo_slide_normalization_requests(presentation))
    requests.extend(build_walkout_slide_cleanup_requests(presentation))
    requests.extend(
        build_anniversary_slide_update_requests(config, presentation, next_demo_date)
    )

    return requests


def build_ordered_slide_blocks(presentation: dict, should_rotate: bool) -> list[list[str]]:
    template_blocks = parse_middle_blocks(presentation)
    presenter_blocks = [
        block for block in template_blocks if block.block_kind == "presenter"
    ]
    active_presenter_blocks = [block for block in presenter_blocks if not block.is_skipped]
    skipped_presenter_blocks = [block for block in presenter_blocks if block.is_skipped]
    ordered_presenter_blocks = [
        *rotate_slide_blocks(active_presenter_blocks, should_rotate),
        *skipped_presenter_blocks,
    ]

    presenter_block_index = 0
    ordered: list[list[str]] = []
    for block in template_blocks:
        if block.block_kind != "presenter":
            ordered.append(block.slide_ids)
            continue
        if presenter_block_index >= len(ordered_presenter_blocks):
            ordered.append(block.slide_ids)
            continue
        ordered.append(ordered_presenter_blocks[presenter_block_index].slide_ids)
        presenter_block_index += 1

    return ordered


def build_reorder_diagnostics(presentation: dict, should_rotate: bool) -> dict:
    template_blocks = parse_middle_blocks(presentation)
    presenter_blocks = [
        block for block in template_blocks if block.block_kind == "presenter"
    ]
    anchored_blocks = [
        block for block in template_blocks if block.block_kind != "presenter"
    ]

    return {
        "presenterBlocksBeforeRotation": describe_blocks(
            presenter_blocks, presentation
        ),
        "activePresenterBlocksBeforeRotation": describe_blocks(
            [block for block in presenter_blocks if not block.is_skipped], presentation
        ),
        "skippedPresenterBlocks": describe_blocks(
            [block for block in presenter_blocks if block.is_skipped], presentation
        ),
        "presenterBlocksAfterRotation": describe_blocks(
            [
                *rotate_slide_blocks(
                    [block for block in presenter_blocks if not block.is_skipped],
                    should_rotate,
                ),
                *[block for block in presenter_blocks if block.is_skipped],
            ],
            presentation,
        ),
        "anchoredBlocks": describe_blocks(anchored_blocks, presentation),
    }


def parse_middle_blocks(presentation: dict) -> list[SlideBlock]:
    slides = presentation.get("slides", [])
    middle = slides[FIXED_SLIDES_AT_START : len(slides) - FIXED_SLIDES_AT_END]

    blocks: list[SlideBlock] = []
    index = 0
    while index < len(middle):
        slide = middle[index]
        text = slide_text(slide)

        if is_protected_slide(text):
            blocks.append(
                SlideBlock(
                    slide_ids=[slide["objectId"]],
                    team_key=detect_team_key(text),
                    block_kind="anchored",
                )
            )
            index += 1
            continue

        if is_demo_slide(text):
            blocks.append(
                SlideBlock(
                    slide_ids=[slide["objectId"]],
                    team_key=None,
                    block_kind="anchored",
                )
            )
            index += 1
            continue

        block_ids = [slide["objectId"]]
        team_key = detect_team_key(text)
        next_index = index + 1
        while next_index < len(middle):
            next_text = slide_text(middle[next_index])
            if is_protected_slide(next_text) or not is_demo_slide(next_text):
                break
            block_ids.append(middle[next_index]["objectId"])
            next_index += 1

        blocks.append(
            SlideBlock(
                slide_ids=block_ids,
                team_key=team_key,
                block_kind="presenter",
                is_skipped=is_skipped_slide(slide),
            )
        )
        index = next_index

    return blocks


def describe_blocks(blocks: list[SlideBlock], presentation: dict) -> list[dict]:
    slide_details_by_id = build_slide_details_by_id(presentation)
    described: list[dict] = []
    for block in blocks:
        described.append(
            {
                "kind": block.block_kind,
                "teamKey": block.team_key,
                "isSkipped": block.is_skipped,
                "slideCount": len(block.slide_ids),
                "slides": [
                    slide_details_by_id.get(
                        slide_id,
                        {
                            "objectId": slide_id,
                            "slideNumber": None,
                            "textPreview": [],
                        },
                    )
                    for slide_id in block.slide_ids
                ],
            }
        )
    return described


def build_slide_details_by_id(presentation: dict) -> dict[str, dict]:
    details: dict[str, dict] = {}
    for index, slide in enumerate(presentation.get("slides", []), start=1):
        details[slide["objectId"]] = {
            "objectId": slide["objectId"],
            "slideNumber": index,
            "textPreview": slide_text(slide).splitlines()[:6],
        }
    return details


def rotate_slide_blocks(
    slide_blocks: list[SlideBlock], should_rotate: bool
) -> list[SlideBlock]:
    if not should_rotate or len(slide_blocks) < 2:
        return list(slide_blocks)
    return [slide_blocks[-1], *slide_blocks[:-1]]


def is_skipped_slide(slide: dict) -> bool:
    slide_properties = slide.get("slideProperties", {})
    return bool(slide_properties.get("isSkipped"))


def detect_team_key(text: str) -> str | None:
    team = detect_team(text)
    return team.key if team else None


def is_demo_slide(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    first_two = [line.lower() for line in lines[:2]]
    joined = "\n".join(lines).lower()
    has_demo_heading = any(line.startswith("demo") for line in first_two)
    has_who = "who" in joined
    has_what = "what" in joined
    return has_demo_heading and has_who and has_what


def is_protected_slide(text: str) -> bool:
    normalized = text.lower()
    protected_markers = [
        "anniversary",
        "feliz aniversario",
        "happy anniversary",
        "joyeux anniversaire",
        "walkout",
        "security banter",
        "security schmooze",
    ]
    return any(marker in normalized for marker in protected_markers)


def detect_team(text: str) -> TeamConfig | None:
    for team in TEAM_CONFIGS:
        for pattern in team.anchor_patterns:
            if re.search(pattern, text, flags=re.I | re.M):
                return team
    return None


def collect_text(node: dict) -> list[str]:
    lines: list[str] = []
    if "shape" in node:
        for text_element in node.get("shape", {}).get("text", {}).get("textElements", []):
            text_run = text_element.get("textRun")
            if text_run:
                content = text_run.get("content", "").strip()
                if content:
                    lines.append(content)

    if "table" in node:
        for row in node.get("table", {}).get("tableRows", []):
            for cell in row.get("tableCells", []):
                lines.extend(collect_text(cell))

    return lines


def shape_text(shape: dict) -> str:
    chunks: list[str] = []
    for text_element in shape.get("text", {}).get("textElements", []):
        text_run = text_element.get("textRun")
        if text_run:
            chunks.append(text_run.get("content", ""))
    return "".join(chunks)


def slide_text(slide: dict) -> str:
    chunks: list[str] = []
    for element in slide.get("pageElements", []):
        chunks.extend(collect_text(element))
    return "\n".join(chunks)


def build_demo_slide_reset_requests(presentation: dict) -> list[dict]:
    return []


def build_team_slide_body_cleanup_requests(presentation: dict) -> list[dict]:
    requests: list[dict] = []
    slide_by_id = {
        slide["objectId"]: slide for slide in presentation.get("slides", [])
    }

    for block in parse_middle_blocks(presentation):
        if block.block_kind != "presenter":
            continue
        title_slide = slide_by_id.get(block.slide_ids[0])
        if not title_slide:
            continue
        requests.extend(build_single_team_slide_cleanup_requests(title_slide))

    return requests


def build_single_team_slide_cleanup_requests(slide: dict) -> list[dict]:
    requests: list[dict] = []
    for element in slide.get("pageElements", []):
        object_id = element.get("objectId")
        shape = element.get("shape")
        if not object_id or not shape:
            continue

        original_text = shape_text(shape)
        if not original_text.strip():
            continue

        if is_shape_just_header(original_text):
            continue

        requests.extend(
            build_team_shape_cleanup_requests(object_id, shape, original_text)
        )

    return requests


def build_team_shape_cleanup_requests(
    object_id: str, shape: dict, original_text: str
) -> list[dict]:
    stripped = original_text.strip()
    if "\n" not in original_text:
        return build_single_line_team_cleanup_requests(object_id, shape, stripped)

    lines = summarize_shape_lines(shape, original_text)
    if len(lines) <= 1:
        return []

    first_line = lines[0]
    return build_fixed_range_delete_requests(
        object_id, shape, [(first_line.end, len(original_text))]
    )


def build_single_line_team_cleanup_requests(
    object_id: str, shape: dict, text: str
) -> list[dict]:
    if is_shape_just_header(text):
        return []

    colon_match = re.match(r"^([^:\n]{1,40}:\s*)(.+)$", text)
    if colon_match:
        start = colon_match.start(2)
        end = colon_match.end(2)
        return build_fixed_range_delete_requests(object_id, shape, [(start, end)])

    if "http" in text.lower():
        url_match = re.search(r"https?://\S+", text, flags=re.I)
        if url_match:
            return build_fixed_range_delete_requests(
                object_id, shape, [(url_match.start(), url_match.end())]
            )

    if len(text) > 50:
        return [build_clear_text_request(object_id)]

    return []


def summarize_shape_lines(shape: dict, original_text: str) -> list[ShapeLine]:
    lines: list[ShapeLine] = []
    cursor = 0
    text_elements = shape.get("text", {}).get("textElements", [])

    for raw_line in original_text.splitlines(keepends=True):
        start = cursor
        end = cursor + len(raw_line)
        cursor = end

        text = raw_line.rstrip("\n\r\v\f")
        if not text.strip():
            continue

        line_is_bold = False
        for item in text_elements:
            text_run = item.get("textRun")
            if not text_run:
                continue
            style = text_run.get("style", {})
            item_start = item.get("startIndex", 0) or 0
            item_end = item.get("endIndex", item_start)
            if item_end <= start or item_start >= end:
                continue
            if style.get("bold"):
                line_is_bold = True
                break

        lines.append(
            ShapeLine(
                text=text.strip(),
                start=start,
                end=end,
                is_bold=line_is_bold,
                word_count=len(text.strip().split()),
            )
        )

    return lines


def build_fixed_range_delete_requests(
    object_id: str, shape: dict, ranges: list[tuple[int, int]]
) -> list[dict]:
    requests: list[dict] = []
    text_length = max_deletable_text_index(shape, shape_text(shape))
    seen: set[tuple[int, int]] = set()
    for start, end in reversed(ranges):
        if (start, end) in seen:
            continue
        seen.add((start, end))
        start = max(0, min(start, text_length))
        end = max(start, min(end, text_length))
        if end <= start:
            continue
        requests.append(
            {
                "deleteText": {
                    "objectId": object_id,
                    "textRange": {
                        "type": "FIXED_RANGE",
                        "startIndex": start,
                        "endIndex": end,
                    },
                }
            }
        )
    return requests


def is_shape_just_header(text: str) -> bool:
    normalized = text.strip()
    if not normalized:
        return True
    if "\n" in normalized:
        return False
    if "http" in normalized.lower():
        return False
    if normalized.endswith(":"):
        return True
    if normalized.endswith((".", "?", "!")):
        return False
    return len(normalized) <= 40


def build_demo_slide_normalization_requests(presentation: dict) -> list[dict]:
    requests: list[dict] = []
    slide_by_id = {
        slide["objectId"]: slide for slide in presentation.get("slides", [])
    }

    for block in parse_middle_blocks(presentation):
        if block.block_kind != "presenter":
            continue

        title_slide = slide_by_id.get(block.slide_ids[0])
        if not title_slide:
            continue

        demo_slide_ids = block.slide_ids[1:]
        if not demo_slide_ids:
            continue

        special_team = is_special_demo_team(slide_text(title_slide))
        kept_demo_slide = slide_by_id.get(demo_slide_ids[0])
        if kept_demo_slide:
            requests.extend(
                build_single_demo_slide_cleanup_requests(
                    kept_demo_slide, keep_images=special_team
                )
            )

        for demo_slide_id in demo_slide_ids[1:]:
            requests.append({"deleteObject": {"objectId": demo_slide_id}})

    return requests


def build_walkout_slide_cleanup_requests(presentation: dict) -> list[dict]:
    requests: list[dict] = []
    walkout_slide = find_walkout_slide(presentation)
    if not walkout_slide:
        return requests

    for element in walkout_slide.get("pageElements", []):
        object_id = element.get("objectId")
        if not object_id:
            continue

        if "video" in element:
            requests.append({"deleteObject": {"objectId": object_id}})
            continue

        if "image" in element and looks_like_walkout_photo(element):
            requests.append({"deleteObject": {"objectId": object_id}})
            continue

        shape = element.get("shape")
        if not shape:
            continue

        original_text = shape_text(shape)
        if not original_text.strip():
            continue

        if "today’s walk-out song brought to you by:" in original_text.lower():
            requests.extend(
                build_walkout_title_cleanup_requests(object_id, shape, original_text)
            )
            continue

        if "time at red hat:" in original_text.lower() and "fun fact:" in original_text.lower():
            requests.extend(
                build_walkout_detail_cleanup_requests(object_id, shape, original_text)
            )

    return requests


def build_anniversary_slide_update_requests(
    config: AppConfig, presentation: dict, next_demo_date: datetime
) -> list[dict]:
    requests: list[dict] = []
    anniversary_slides = find_anniversary_slides(presentation)
    if not anniversary_slides:
        return requests

    kept_slide = anniversary_slides[0]
    extra_slides = anniversary_slides[1:]
    anniversary_entries = load_upcoming_anniversaries(
        config, presentation, next_demo_date
    )
    name_shapes = find_anniversary_name_shapes(anniversary_slides)

    for slide in extra_slides:
        requests.append({"deleteObject": {"objectId": slide["objectId"]}})

    for element in kept_slide.get("pageElements", []):
        object_id = element.get("objectId")
        if not object_id:
            continue

        image = element.get("image")
        if image and looks_like_anniversary_portrait(element):
            requests.append({"deleteObject": {"objectId": object_id}})

    if not name_shapes:
        return requests

    primary_shape = name_shapes[0]
    requests.append(build_clear_text_request(primary_shape["objectId"]))
    if anniversary_entries:
        requests.extend(
            build_anniversary_textbox_requests(
                kept_slide_id=kept_slide["objectId"],
                template_shape=primary_shape,
                anniversaries=anniversary_entries,
                page_size=presentation.get("pageSize", {}),
            )
        )

    return requests


def find_anniversary_slides(presentation: dict) -> list[dict]:
    items: list[dict] = []
    for slide in presentation.get("slides", []):
        if is_anniversary_slide(slide_text(slide)):
            items.append(slide)
    return items


def find_walkout_slide(presentation: dict) -> dict | None:
    for slide in presentation.get("slides", []):
        if is_walkout_slide(slide_text(slide)):
            return slide
    return None


def is_walkout_slide(text: str) -> bool:
    normalized = text.lower()
    return (
        "today’s walk-out song brought to you by:" in normalized
        or "today's walk-out song brought to you by:" in normalized
    ) and "time at red hat:" in normalized and "fun fact:" in normalized


def is_anniversary_slide(text: str) -> bool:
    normalized = text.lower()
    markers = [
        "happy anniversary",
        "feliz aniversario",
        "joyeux anniversaire",
        "šťastné výročí",
    ]
    return any(marker in normalized for marker in markers)


def looks_like_anniversary_portrait(element: dict) -> bool:
    size = element.get("size", {})
    width = size.get("width", {}).get("magnitude")
    height = size.get("height", {}).get("magnitude")
    if not width or not height:
        return False
    return width == height


def looks_like_walkout_photo(element: dict) -> bool:
    size = element.get("size", {})
    transform = element.get("transform", {})
    width = (size.get("width", {}) or {}).get("magnitude")
    height = (size.get("height", {}) or {}).get("magnitude")
    scale_x = abs(transform.get("scaleX", 1))
    scale_y = abs(transform.get("scaleY", 1))
    if not width or not height:
        return False
    rendered_width = width * scale_x
    rendered_height = height * scale_y
    return rendered_width >= 1800000 and rendered_height >= 1800000


def find_anniversary_name_shapes(slides: list[dict]) -> list[dict]:
    shapes: list[dict] = []
    for slide in slides:
        for element in slide.get("pageElements", []):
            shape = element.get("shape")
            object_id = element.get("objectId")
            if not shape or not object_id:
                continue
            text = shape_text(shape).strip()
            if not text:
                continue
            if re.search(r",\s*\d+\s+year", text, flags=re.I):
                shapes.append(
                    {
                        "objectId": object_id,
                        "size": element.get("size"),
                        "transform": element.get("transform"),
                    }
                )
    return shapes


def build_anniversary_textbox_requests(
    *,
    kept_slide_id: str,
    template_shape: dict,
    anniversaries,
    page_size: dict,
) -> list[dict]:
    requests: list[dict] = []

    base_transform = dict(template_shape.get("transform") or {})
    size = dict(template_shape.get("size") or {})
    if not base_transform or not size:
        return requests

    layout = build_anniversary_text_layout(
        base_transform, size, len(anniversaries), page_size
    )

    for index, item in enumerate(anniversaries):
        object_id = (
            template_shape["objectId"]
            if index == 0
            else f"{template_shape['objectId']}_anniv_{index + 1}"
        )
        transform = layout[index]
        if index == 0:
            requests.append(
                {
                    "updatePageElementTransform": {
                        "objectId": object_id,
                        "applyMode": "ABSOLUTE",
                        "transform": transform,
                    }
                }
            )
        else:
            requests.append(
                {
                    "createShape": {
                        "objectId": object_id,
                        "shapeType": "TEXT_BOX",
                        "elementProperties": {
                            "pageObjectId": kept_slide_id,
                            "size": size,
                            "transform": transform,
                        },
                    }
                }
            )

        requests.append(
            {
                "insertText": {
                    "objectId": object_id,
                    "insertionIndex": 0,
                    "text": format_anniversary_text(item),
                }
            }
        )
        requests.append(build_anniversary_text_style_request(object_id))

    return requests


def build_anniversary_text_layout(
    base_transform: dict, size: dict, count: int, page_size: dict
) -> list[dict]:
    if count <= 0:
        return []

    page_width = (
        page_size.get("width", {}).get("magnitude")
        if isinstance(page_size.get("width"), dict)
        else None
    ) or 9144000
    rendered_width = int(
        (
            size.get("width", {}).get("magnitude")
            if isinstance(size.get("width"), dict)
            else 3000000
        )
        * abs(base_transform.get("scaleX", 1))
    )
    margin = 450000
    available_gap = page_width - (count * rendered_width) - (2 * margin)
    gap = 250000
    if count > 1:
        gap = max(150000, int(available_gap / (count - 1)))

    total_group_width = (count * rendered_width) + ((count - 1) * gap)
    start_x = int((page_width - total_group_width) / 2)
    row_y = 3650000 if count >= 3 else 3900000

    layout: list[dict] = []
    for index in range(count):
        transform = dict(base_transform)
        transform["translateX"] = start_x + (index * (rendered_width + gap))
        transform["translateY"] = row_y
        layout.append(transform)
    return layout


def format_anniversary_text(item) -> str:
    label = "year" if item.years == 1 else "years"
    return f"{item.name}, {item.years} {label}!!"


def build_anniversary_text_style_request(object_id: str) -> dict:
    return {
        "updateTextStyle": {
            "objectId": object_id,
            "style": {
                "fontFamily": "Arial",
                "fontSize": {"magnitude": 16, "unit": "PT"},
                "foregroundColor": {
                    "opaqueColor": {"rgbColor": {"red": 1, "green": 1, "blue": 1}}
                },
            },
            "textRange": {"type": "ALL"},
            "fields": "fontFamily,fontSize,foregroundColor",
        }
    }


def build_clear_text_request(object_id: str) -> dict:
    return {
        "deleteText": {
            "objectId": object_id,
            "textRange": {"type": "ALL"},
        }
    }


def build_walkout_title_cleanup_requests(
    object_id: str, shape: dict, original_text: str
) -> list[dict]:
    title_patterns = [
        r"(?is)(Today[’']s Walk-Out Song Brought to You by:\s*)(.*)",
    ]
    return build_text_range_deletion_requests(
        object_id, shape, original_text, title_patterns, capture_group=2
    )


def build_walkout_detail_cleanup_requests(
    object_id: str, shape: dict, original_text: str
) -> list[dict]:
    patterns = [
        r"(?is)(Time at Red Hat:\s*)(.*?)(?=\s*[\r\n\v\f]+?\s*Fun Fact:|\s*Fun Fact:|\Z)",
        r"(?is)(Fun Fact:\s*)(.*?)(?=\Z)",
    ]
    return build_text_range_deletion_requests(
        object_id, shape, original_text, patterns, capture_group=2
    )


def build_text_range_deletion_requests(
    object_id: str,
    shape: dict,
    original_text: str,
    patterns: list[str],
    *,
    capture_group: int,
) -> list[dict]:
    requests: list[dict] = []
    text_length = max_deletable_text_index(shape, original_text)
    ranges: list[tuple[int, int]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, original_text):
            value = match.group(capture_group)
            if not value or not value.strip():
                continue
            start = match.start(capture_group)
            end = match.end(capture_group)
            ranges.append((start, end))

    seen: set[tuple[int, int]] = set()
    for start, end in reversed(ranges):
        if (start, end) in seen:
            continue
        seen.add((start, end))
        start = max(0, min(start, text_length))
        end = max(start, min(end, text_length))
        if end <= start:
            continue
        requests.append(
            {
                "deleteText": {
                    "objectId": object_id,
                    "textRange": {
                        "type": "FIXED_RANGE",
                        "startIndex": start,
                        "endIndex": end,
                    },
                }
            }
        )
    return requests


def load_upcoming_anniversaries(
    config: AppConfig, presentation: dict, next_demo_date: datetime
):
    from .csv_support import read_csv_records
    from .planner import Anniversary, parse_date

    csv_path = config.default_hire_dates_csv
    if not csv_path or not Path(csv_path).exists():
        return []

    _, previous_end_text = parse_cover_range(presentation)
    if previous_end_text:
        previous_demo_date = datetime.strptime(previous_end_text, "%b %d, %Y").date()
    else:
        previous_demo_date = (
            next_demo_date - timedelta(days=config.next_deck_date_offset_days)
        ).date()

    records = read_csv_records(csv_path)
    next_demo_day = next_demo_date.date()
    anniversaries: list[Anniversary] = []

    for row in records:
        name = row.get("name", "").strip()
        hire_date = parse_date(row.get("hire date", ""))
        if not name or hire_date is None:
            continue

        anniversary = hire_date.replace(year=next_demo_day.year).date()
        if anniversary <= previous_demo_date:
            anniversary = hire_date.replace(year=next_demo_day.year + 1).date()

        if anniversary > next_demo_day:
            continue

        anniversaries.append(
            Anniversary(
                name=name,
                hire_date=hire_date.date().isoformat(),
                anniversary_date=anniversary.isoformat(),
                years=anniversary.year - hire_date.year,
            )
        )

    return sorted(anniversaries, key=lambda item: (item.anniversary_date, item.name.lower()))


def reset_demo_shape_text(original_text: str) -> str | None:
    text = original_text.replace("\r", "")
    if not text.strip():
        return None

    updated = text
    patterns = [
        (
            r"(?is)(Who\s*\n\s*:)\s*.*?(?=\n\s*What\b|\n\s*I am demo-?ing this because\b|\n\s*Demo Content\b|\Z)",
            r"\1",
        ),
        (
            r"(?is)(Who\s*:)\s*.*?(?=\n\s*What\b|\n\s*I am demo-?ing this because\b|\n\s*Demo Content\b|\Z)",
            r"\1",
        ),
        (
            r"(?is)(Who:\s*)\S.*?(?=\n\s*What\b|\n\s*I am demo-?ing this because\b|\n\s*Demo Content\b|\Z)",
            r"\1",
        ),
        (
            r"(?is)(What\s*\n\s*:)\s*.*?(?=\n\s*I am demo-?ing this because\b|\n\s*Demo Content\b|\Z)",
            r"\1",
        ),
        (
            r"(?is)(What\s*:)\s*.*?(?=\n\s*I am demo-?ing this because\b|\n\s*Demo Content\b|\Z)",
            r"\1",
        ),
        (
            r"(?is)(What:\s*)\S.*?(?=\n\s*I am demo-?ing this because\b|\n\s*Demo Content\b|\Z)",
            r"\1",
        ),
        (
            r"(?is)(I am demo-?ing this because\s*\n\s*:)\s*.*?(?=\n\s*Demo Content\b|\Z)",
            r"\1",
        ),
        (
            r"(?is)(I am demo-?ing this because\s*:)\s*.*?(?=\n\s*Demo Content\b|\Z)",
            r"\1",
        ),
    ]

    for pattern, replacement in patterns:
        updated = re.sub(pattern, replacement, updated)

    return updated


def build_single_demo_slide_cleanup_requests(
    slide: dict, *, keep_images: bool
) -> list[dict]:
    requests: list[dict] = []
    for element in slide.get("pageElements", []):
        object_id = element.get("objectId")
        if not object_id:
            continue

        shape = element.get("shape")
        image = element.get("image")
        video = element.get("video")

        if image:
            if not keep_images:
                requests.append({"deleteObject": {"objectId": object_id}})
            continue

        if video:
            requests.append({"deleteObject": {"objectId": object_id}})
            continue

        if not shape:
            continue

        original_text = shape_text(shape)
        if not original_text.strip():
            continue

        if is_demo_content_shape(original_text):
            continue

        if looks_like_demo_label_shape(original_text):
            requests.extend(
                build_answer_deletion_requests(object_id, shape, original_text)
            )
            continue

        requests.append({"deleteObject": {"objectId": object_id}})

    return requests


def build_answer_deletion_requests(
    object_id: str, shape: dict, original_text: str
) -> list[dict]:
    requests: list[dict] = []
    text_length = max_deletable_text_index(shape, original_text)
    for start, end in reversed(find_demo_answer_ranges(original_text)):
        start = max(0, min(start, text_length))
        end = max(start, min(end, text_length))
        if end <= start:
            continue
        requests.append(
            {
                "deleteText": {
                    "objectId": object_id,
                    "textRange": {
                        "type": "FIXED_RANGE",
                        "startIndex": start,
                        "endIndex": end,
                    },
                }
            }
        )
    return requests


def max_deletable_text_index(shape: dict, original_text: str) -> int:
    text_elements = shape.get("text", {}).get("textElements", [])
    max_end = max((item.get("endIndex", 0) for item in text_elements), default=0)
    if max_end <= 0:
        return len(original_text)
    return max(0, max_end - 1)


def find_demo_answer_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    patterns = [
        r"(?is)(Who\s*:)(.*?)(?=\n\s*What\b|\n\s*I am demo-?ing this because\b|\n\s*Demo Content\b|\Z)",
        r"(?is)(Who\s*\n\s*:)(.*?)(?=\n\s*What\b|\n\s*I am demo-?ing this because\b|\n\s*Demo Content\b|\Z)",
        r"(?is)(What\s*:)(.*?)(?=\n\s*I am demo-?ing this because\b|\n\s*Demo Content\b|\Z)",
        r"(?is)(What\s*\n\s*:)(.*?)(?=\n\s*I am demo-?ing this because\b|\n\s*Demo Content\b|\Z)",
        r"(?is)(I am demo-?ing this because\s*:)(.*?)(?=\n\s*Demo Content\b|\Z)",
        r"(?is)(I am demo-?ing this because\s*\n\s*:)(.*?)(?=\n\s*Demo Content\b|\Z)",
    ]

    for pattern in patterns:
        for match in re.finditer(pattern, text):
            answer = match.group(2)
            if not answer:
                continue
            start = match.start(2)
            end = match.end(2)
            if text[start:end].strip():
                ranges.append((start, end))

    deduped: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    for item in ranges:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def looks_like_demo_label_shape(text: str) -> bool:
    normalized = text.lower()
    return "who" in normalized and ("what" in normalized or "demo" in normalized)


def is_demo_content_shape(text: str) -> bool:
    return text.strip().lower().startswith("demo content")


def is_special_demo_team(text: str) -> bool:
    normalized = text.lower()
    return "hcc app framework" in normalized or "sprinkles" in normalized


def parse_cover_range(presentation: dict) -> tuple[str | None, str | None]:
    first_slide = presentation.get("slides", [])[0]
    text = slide_text(first_slide)
    match = re.search(
        r"([A-Z][a-z]{2,8}\s+\d{1,2})\s*-\s*([A-Z][a-z]{2,8}\s+\d{1,2},\s+\d{4})",
        text,
    )
    if not match:
        return None, None
    return match.group(0), match.group(2)


def format_cover_range(previous_end_text: str, next_demo: datetime) -> str:
    previous_end = datetime.strptime(previous_end_text, "%b %d, %Y")
    new_start = previous_end + timedelta(days=1)
    new_end = next_demo.replace(tzinfo=None)
    return (
        f"{new_start.strftime('%b')} {new_start.day} - "
        f"{new_end.strftime('%b')} {new_end.day}, {new_end.year}"
    )


def build_new_file_name(source_name: str, next_demo: datetime) -> str:
    source_name = re.sub(r"^Copy of\s+", "", source_name, flags=re.I)
    suffix = next_demo.strftime("%m%d%y")
    updated = re.sub(r"_\d{6}$", f"_{suffix}", source_name)
    if updated != source_name:
        return updated
    return f"{source_name} - {next_demo.strftime('%Y-%m-%d')}"
