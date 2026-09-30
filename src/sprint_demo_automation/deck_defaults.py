from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TeamConfig:
    key: str
    anchor_patterns: list[str]
    block_size: int = 2


FIXED_SLIDES_AT_START = 3
FIXED_SLIDES_AT_END = 2

GLOBAL_REPLACEMENTS: list[tuple[str, str]] = [
    ("<Insert Name Here>", ""),
    ("http://10.0.77.89:3000", ""),
]

TEAM_CONFIGS: list[TeamConfig] = [
    TeamConfig("performance-and-scalability", [r"^Performance and Scalability\b"], 3),
    TeamConfig(
        "platform-experience-services",
        [
            r"Added Workspace selector to the chrome header",
            r"Dashboard hub in production",
        ],
        2,
    ),
    TeamConfig("console-next", [r"Console Next Team", r"^Last Sprint Highlights\b"], 2),
    TeamConfig("kessel", [r"^Kessel\b"], 2),
    TeamConfig("fabric-notifications", [r"Fabric Notificati", r"^Notifications\b"], 2),
    TeamConfig(
        "platform-access-and-management",
        [r"^Platform Access and Management\b", r"^This Sprint.s Goals"],
        2,
    ),
    TeamConfig(
        "console-dot-uxd",
        [r"^Chroming\b", r"^Applied AI\b", r"^Console Dot UXD\b", r"^Console\s+Dot\s+UXD\b"],
        2,
    ),
]
