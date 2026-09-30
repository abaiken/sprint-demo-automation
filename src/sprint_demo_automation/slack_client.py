from __future__ import annotations

import os


def lookup_slack_photo(email: str) -> dict:
    try:
        from slack_sdk import WebClient
    except ModuleNotFoundError as exc:  # pragma: no cover - optional dependency at runtime
        raise RuntimeError(
            "slack-sdk is not installed. Install project dependencies first."
        ) from exc

    token = os.environ.get("SLACK_BOT_TOKEN") or os.environ.get("SLACK_USER_TOKEN")
    if not token:
        raise RuntimeError(
            "Set SLACK_BOT_TOKEN or SLACK_USER_TOKEN to look up Slack profile photos."
        )

    client = WebClient(token=token)
    result = client.users_lookupByEmail(email=email)
    user = result["user"]
    profile = user.get("profile", {})
    return {
        "id": user.get("id", ""),
        "real_name": user.get("real_name", ""),
        "display_name": profile.get("display_name", ""),
        "email": profile.get("email", ""),
        "image_512": profile.get("image_512", ""),
        "image_192": profile.get("image_192", ""),
        "title": profile.get("title", ""),
    }
