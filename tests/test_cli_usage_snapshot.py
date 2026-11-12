"""Snapshot of argparse's ``usage:`` block.

Adding any flag changes this block.  This file is the one place phase 05 may
update deliberately (see plan/DECISIONS.md, D4); test_cli_contract.py only
pins the final ``fomo: error: …`` line of usage errors.
"""

from __future__ import annotations

USAGE = [
    "usage: fomo [-h] [-r TEXT] [-t DURATION] [--dry-run] [--entra]",
    "            [--mg MANAGEMENT_GROUP] [--demo] [--log FILE]",
    "            [ARG ...]",
]


def test_usage_block_on_usage_error(run_cli, fake_azure) -> None:
    """U1 prints the usage block, then the error line, on stderr."""
    code, out, err = run_cli(["Reader", "-r", "x"])
    assert code == 2
    assert out == []
    assert err == [
        *USAGE,
        "fomo: error: Provide SUBSCRIPTION ROLE as positional arguments when using --reason/-r",
    ]


def test_help_first_line(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["-h"])
    assert code == 0
    assert err == []
    assert out[0] == USAGE[0]
    assert out[: len(USAGE)] == USAGE
