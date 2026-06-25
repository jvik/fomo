"""Tests for CLI non-interactive mode: duration parsing and argument handling."""

from __future__ import annotations

import pytest

from fzf_pim.azure import parse_duration
from fzf_pim.__main__ import build_parser


# ---------------------------------------------------------------------------
# parse_duration
# ---------------------------------------------------------------------------

def test_parse_duration_minutes() -> None:
    assert parse_duration("30m") == "PT30M"


def test_parse_duration_hours() -> None:
    assert parse_duration("1h") == "PT1H"
    assert parse_duration("8h") == "PT8H"


def test_parse_duration_hours_and_minutes() -> None:
    assert parse_duration("1h30m") == "PT1H30M"
    assert parse_duration("2h15m") == "PT2H15M"


def test_parse_duration_case_insensitive() -> None:
    assert parse_duration("30M") == "PT30M"
    assert parse_duration("1H") == "PT1H"
    assert parse_duration("2H30M") == "PT2H30M"


def test_parse_duration_iso8601_passthrough() -> None:
    assert parse_duration("PT1H") == "PT1H"
    assert parse_duration("PT30M") == "PT30M"
    assert parse_duration("PT2H30M") == "PT2H30M"
    assert parse_duration("PT8H") == "PT8H"


def test_parse_duration_invalid_raises() -> None:
    with pytest.raises(ValueError, match="Invalid duration"):
        parse_duration("invalid")


def test_parse_duration_empty_raises() -> None:
    with pytest.raises(ValueError, match="Invalid duration"):
        parse_duration("")


def test_parse_duration_days_unsupported() -> None:
    # Days are not supported in the shorthand format
    with pytest.raises(ValueError, match="Invalid duration"):
        parse_duration("1d")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def test_parser_defaults_tui_mode() -> None:
    """No positional args → TUI mode (reason is None)."""
    args = build_parser().parse_args([])
    assert args.reason is None
    assert args.positional == []
    assert args.duration == "PT1H"
    assert not args.dry_run
    assert not args.entra


def test_parser_cli_mode_role_only() -> None:
    args = build_parser().parse_args(["Key Vault Administrator", "-r", "Break-glass"])
    assert args.positional == ["Key Vault Administrator"]
    assert args.reason == "Break-glass"
    assert args.duration == "PT1H"


def test_parser_cli_mode_with_subscription() -> None:
    args = build_parser().parse_args(
        ["my-sub", "Key Vault Administrator", "-r", "Break-glass", "-t", "30m"]
    )
    assert args.positional == ["my-sub", "Key Vault Administrator"]
    assert args.reason == "Break-glass"
    assert args.duration == "30m"


def test_parser_dry_run_flag() -> None:
    args = build_parser().parse_args(
        ["Key Vault Administrator", "-r", "test", "--dry-run"]
    )
    assert args.dry_run is True
    assert args.reason == "test"


def test_parser_long_flags() -> None:
    args = build_parser().parse_args(
        ["my-sub", "Reader", "--reason", "routine", "--time", "2h"]
    )
    assert args.positional == ["my-sub", "Reader"]
    assert args.reason == "routine"
    assert args.duration == "2h"
