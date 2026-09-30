from __future__ import annotations

from .config import AppConfig


def build_walkout_form_message(config: AppConfig, candidate_name: str, form_url: str) -> str:
    return (
        f"Hi {candidate_name}! You are the next Demo Day contributor highlight. "
        f"When you have a chance, please fill out the form here: {form_url}"
    )


def build_coordinator_summary_message(
    config: AppConfig,
    *,
    deck_name: str,
    deck_url: str,
    anniversary_count: int,
    walkout_candidate_name: str | None,
) -> str:
    candidate = walkout_candidate_name or "none selected"
    return (
        f"Ceremony prep is ready for review. Deck: {deck_name} ({deck_url}). "
        f"Upcoming anniversaries: {anniversary_count}. Walkout candidate: {candidate}."
    )


def build_walkout_interest_message(candidate_name: str, reason: str | None = None) -> str:
    reason_text = f" ({reason})" if reason else ""
    return (
        f"Hi {candidate_name}! You are the next likely Demo Day contributor highlight"
        f"{reason_text}. Would you be up for doing the walk-out song for this sprint demo?"
    )


def build_mc_request_message(deck_url: str) -> str:
    return (
        f"Hi MCs! The next sprint demo deck is ready: {deck_url} "
        "Could one of you volunteer to MC this round?"
    )
