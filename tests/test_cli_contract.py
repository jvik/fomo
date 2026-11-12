"""Executable contract for the non-interactive CLI (REPORT.md section 1).

Each test is named after its row in the characterization matrix.  These tests
pin what the CLI does *today*, including the odd parts; they must not be
"fixed" to match the docs.  See plan/RULES.md for when they may change.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

from fomo.__main__ import build_parser
from tests.conftest import ROOT_MG, FakeAzure, role

MG_CORP = "/providers/Microsoft.Management/managementGroups/corp"

FETCH_SUBS = "Fetching subscriptions…"
FETCH_MGS = "Fetching management groups…"
FETCH_ENTRA = "Fetching Entra eligible roles…"
INVALID_90 = (
    "Error: Invalid duration '90'. Use e.g. '30m', '1h', '1h30m', "
    "or ISO 8601 like 'PT1H'."
)


def _fetch_roles(n: int) -> str:
    return f"Fetching eligible roles from {n} subscription(s)…"


def _fetch_mg_roles(name: str) -> str:
    return f"Fetching eligible roles for management group '{name}'…"


def _usage_error(run_cli, fake: FakeAzure, argv: list[str], message: str) -> None:
    code, out, err = run_cli(argv)
    assert code == 2
    assert out == []
    assert err[-1] == f"fomo: error: {message}"
    assert fake.calls == []
    assert fake.activations == []


# ---------------------------------------------------------------------------
# Usage errors and common flags (all modes)
# ---------------------------------------------------------------------------


def test_U1_single_positional_with_reason(run_cli, fake_azure) -> None:
    _usage_error(
        run_cli, fake_azure, ["Reader", "-r", "x"],
        "Provide SUBSCRIPTION ROLE as positional arguments when using --reason/-r",
    )


def test_U2_three_positionals_with_reason(run_cli, fake_azure) -> None:
    _usage_error(
        run_cli, fake_azure, ["a", "b", "c", "-r", "x"],
        "Provide SUBSCRIPTION ROLE as positional arguments when using --reason/-r",
    )


def test_U3_positional_without_reason(run_cli, fake_azure) -> None:
    _usage_error(
        run_cli, fake_azure, ["Reader"],
        "Positional arguments require --reason/-r for non-interactive activation",
    )


def test_U4_entra_and_mg_are_exclusive(run_cli, fake_azure) -> None:
    _usage_error(
        run_cli, fake_azure, ["--entra", "--mg", "m", "R", "-r", "x"],
        "--entra and --mg are mutually exclusive",
    )


def test_U5_mg_requires_reason(run_cli, fake_azure) -> None:
    _usage_error(
        run_cli, fake_azure, ["--mg", "m", "R"],
        "--mg requires -r/--reason for non-interactive activation",
    )


def test_U6_entra_requires_exactly_one_positional(run_cli, fake_azure) -> None:
    _usage_error(
        run_cli, fake_azure, ["--entra", "a", "b", "-r", "x"],
        "Provide exactly one positional argument (ROLE) when using --entra --reason/-r",
    )


def test_U7_mg_requires_exactly_one_positional(run_cli, fake_azure) -> None:
    _usage_error(
        run_cli, fake_azure, ["--mg", "m", "a", "b", "-r", "x"],
        "Provide exactly one positional argument (ROLE) when using --mg --reason/-r",
    )


@pytest.mark.parametrize(
    "argv",
    [
        ["Production", "Reader", "-r", "x", "-t", "90"],
        ["--mg", "Corp", "Reader", "-r", "x", "--time", "90"],
        ["--entra", "Reader", "-r", "x", "-t", "90"],
    ],
    ids=["subscription", "mg", "entra"],
)
def test_U8_invalid_duration(run_cli, fake_azure, argv) -> None:
    code, out, err = run_cli(argv)
    assert code == 1
    assert out == []
    assert err == [INVALID_90]
    assert fake_azure.calls == []
    assert fake_azure.activations == []


def _option(parser: argparse.ArgumentParser, dest: str) -> argparse.Action:
    (action,) = [a for a in parser._actions if a.dest == dest]
    return action


def test_U9_parser_shape(run_cli, fake_azure) -> None:
    parser = build_parser()
    assert parser.prog == "fomo"

    expected = {
        # dest: (option_strings, default, metavar)
        "help": (["-h", "--help"], argparse.SUPPRESS, None),
        "reason": (["-r", "--reason"], None, "TEXT"),
        "duration": (["-t", "--time"], "PT1H", "DURATION"),
        "dry_run": (["--dry-run"], False, None),
        "entra": (["--entra"], False, None),
        "mg": (["--mg"], None, "MANAGEMENT_GROUP"),
        "demo": (["--demo"], False, None),
        "log": (["--log"], None, "FILE"),
    }
    options = [a for a in parser._actions if a.option_strings]
    assert [a.dest for a in options] == list(expected)
    for dest, (option_strings, default, metavar) in expected.items():
        action = _option(parser, dest)
        assert action.option_strings == option_strings, dest
        assert action.default == default, dest
        assert action.metavar == metavar, dest

    positionals = [a for a in parser._actions if not a.option_strings]
    assert len(positionals) == 1
    (positional,) = positionals
    assert positional.dest == "positional"
    assert positional.nargs == "*"
    assert positional.metavar == "ARG"

    code, out, err = run_cli(["-h"])
    assert code == 0
    assert out[0].startswith("usage: fomo ")
    assert err == []

    code, out, err = run_cli(["--help"])
    assert code == 0
    assert out[0].startswith("usage: fomo ")


@pytest.mark.parametrize(
    "argv, expected_out, expected_act",
    [
        (
            ["Production", "Key Vault Reader", "-r", "x", "--dry-run"],
            [
                FETCH_SUBS,
                _fetch_roles(1),
                "Activating 1 role(s)…",
                "  • Key Vault Reader  —  s1… ✓ DryRun",
            ],
            [("Key Vault Reader", "/subscriptions/s1", "PT1H", True)],
        ),
        (
            ["--mg", "Corp", "Reader", "-r", "x", "--dry-run"],
            [
                FETCH_MGS,
                _fetch_mg_roles("Corp"),
                "Activating 1 role(s)…",
                "  • Reader  —  corp… ✓ DryRun",
            ],
            [("Reader", MG_CORP, "PT1H", True)],
        ),
        (
            ["--entra", "Global Reader", "-r", "x", "--dry-run"],
            [
                FETCH_ENTRA,
                "Activating 1 Entra role(s)…",
                "  • Global Reader… ✓ DryRun",
            ],
            [("Global Reader", "/", "PT1H", True)],
        ),
    ],
    ids=["subscription", "mg", "entra"],
)
def test_U10_dry_run_passes_through(
    run_cli, fake_azure, argv, expected_out, expected_act
) -> None:
    code, out, err = run_cli(argv)
    assert code == 0
    assert out == expected_out
    assert err == []
    assert fake_azure.activations == expected_act


def test_U11_build_parser_loads_standalone(monkeypatch) -> None:
    """hatch_build.py executes fomo/__main__.py without fomo or textual importable."""
    import fomo

    path = Path(fomo.__file__).parent / "__main__.py"
    monkeypatch.setitem(sys.modules, "fomo", None)
    monkeypatch.setitem(sys.modules, "textual", None)

    spec = importlib.util.spec_from_file_location("fomo.__main__", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    args = module.build_parser().parse_args([])
    assert args.reason is None
    assert args.duration == "PT1H"


def test_U12_keyboard_interrupt_propagates(run_cli, fake_azure) -> None:
    fake_azure.subs_err = KeyboardInterrupt()
    with pytest.raises(KeyboardInterrupt):
        run_cli(["Production", "Reader", "-r", "x"])
    assert fake_azure.activations == []


# ---------------------------------------------------------------------------
# Subscription mode
# ---------------------------------------------------------------------------


def test_S1_success(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["Production", "Key Vault Reader", "-r", "x"])
    assert code == 0
    assert out == [
        FETCH_SUBS,
        _fetch_roles(1),
        "Activating 1 role(s)…",
        "  • Key Vault Reader  —  s1… ✓ Provisioned",
    ]
    assert err == []
    assert fake_azure.activations == [("Key Vault Reader", "/subscriptions/s1", "PT1H", False)]
    assert fake_azure.justifications == ["x"]


def test_S2_exact_name_beats_substring_across_subs(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["Contoso", "Reader", "-r", "x", "-t", "30m"])
    assert code == 0
    assert out == [
        FETCH_SUBS,
        _fetch_roles(2),
        "Activating 2 role(s)…",
        "  • Reader  —  s1… ✓ Provisioned",
        "  • Reader  —  s2… ✓ Provisioned",
    ]
    assert err == []
    assert fake_azure.activations == [
        ("Reader", "/subscriptions/s1", "PT30M", False),
        ("Reader", "/subscriptions/s2", "PT30M", False),
    ]


def test_S3_exact_match_is_case_insensitive(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["Production", "READER", "-r", "x"])
    assert code == 0
    assert out == [
        FETCH_SUBS,
        _fetch_roles(1),
        "Activating 1 role(s)…",
        "  • Reader  —  s1… ✓ Provisioned",
    ]
    assert err == []
    assert fake_azure.activations == [("Reader", "/subscriptions/s1", "PT1H", False)]


def test_S4_substring_activates_all_matches(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["Production", "Read", "-r", "x"])
    assert code == 0
    assert out == [
        FETCH_SUBS,
        _fetch_roles(1),
        "Activating 2 role(s)…",
        "  • Reader  —  s1… ✓ Provisioned",
        "  • Key Vault Reader  —  s1… ✓ Provisioned",
    ]
    assert err == []
    assert fake_azure.activations == [
        ("Reader", "/subscriptions/s1", "PT1H", False),
        ("Key Vault Reader", "/subscriptions/s1", "PT1H", False),
    ]


def test_S5_exact_subscription_id(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["S2", "Reader", "--reason", "x", "--time", "1h30m"])
    assert code == 0
    assert out == [
        FETCH_SUBS,
        _fetch_roles(1),
        "Activating 1 role(s)…",
        "  • Reader  —  s2… ✓ Provisioned",
    ]
    assert err == []
    assert fake_azure.calls == [("list_subscriptions",), ("list_eligible_roles", "s2")]
    assert fake_azure.activations == [("Reader", "/subscriptions/s2", "PT1H30M", False)]


def test_S6_no_subscription_match(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["nomatch", "Reader", "-r", "x"])
    assert code == 1
    assert out == [FETCH_SUBS]
    assert err == [
        "Error: No subscription matching 'nomatch' found.",
        "Available subscriptions:",
        "  Contoso Production  (s1)",
        "  Contoso Dev  (s2)",
    ]
    assert fake_azure.activations == []


def test_S7_no_role_match(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["Production", "Owner", "-r", "x"])
    assert code == 1
    assert out == [FETCH_SUBS, _fetch_roles(1)]
    assert err == [
        "Error: No eligible role matching 'Owner' found.",
        "Available eligible roles:",
        "  Contributor",
        "  Key Vault Reader",
        "  Reader",
    ]
    assert fake_azure.activations == []


def test_S8_no_roles_after_filtering(run_cli, fake_azure) -> None:
    fake_azure.roles = {"s1": [role("Reader", ROOT_MG, disp="Tenant Root")]}
    code, out, err = run_cli(["Production", "Reader", "-r", "x"])
    assert code == 1
    assert out == [FETCH_SUBS, _fetch_roles(1)]
    assert err == ["Error: No eligible PIM roles found."]
    assert fake_azure.activations == []


def test_S9_inherited_mg_roles_are_dropped(run_cli, fake_azure) -> None:
    # Not activated: only the subscription-scoped Reader is, not the root one.
    code, out, err = run_cli(["Production", "Reader", "-r", "x"])
    assert code == 0
    assert out[-1] == "  • Reader  —  s1… ✓ Provisioned"
    assert fake_azure.activations == [("Reader", "/subscriptions/s1", "PT1H", False)]

    # Not listed: a role that exists only at a parent MG is invisible.
    fake_azure.activations.clear()
    fake_azure.roles["s1"].append(role("Owner", ROOT_MG, disp="Tenant Root"))
    code, out, err = run_cli(["Production", "Owner", "-r", "x"])
    assert code == 1
    assert out == [FETCH_SUBS, _fetch_roles(1)]
    assert err == [
        "Error: No eligible role matching 'Owner' found.",
        "Available eligible roles:",
        "  Contributor",
        "  Key Vault Reader",
        "  Reader",
    ]
    assert fake_azure.activations == []


def test_S10_all_matches_already_active(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["Production", "Contributor", "-r", "x"])
    assert code == 0
    assert out == [
        FETCH_SUBS,
        _fetch_roles(1),
        "All 1 matching role(s) are already active.",
    ]
    assert err == []
    assert fake_azure.activations == []


def test_S11_some_matches_already_active(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["Production", "r", "-r", "x"])
    assert code == 0
    assert out == [
        FETCH_SUBS,
        _fetch_roles(1),
        "Skipping 1 already-active role(s).",
        "Activating 2 role(s)…",
        "  • Reader  —  s1… ✓ Provisioned",
        "  • Key Vault Reader  —  s1… ✓ Provisioned",
    ]
    assert err == []
    assert fake_azure.activations == [
        ("Reader", "/subscriptions/s1", "PT1H", False),
        ("Key Vault Reader", "/subscriptions/s1", "PT1H", False),
    ]


def test_S12_partial_failure(run_cli, fake_azure) -> None:
    fake_azure.fail_on = {"Reader"}
    code, out, err = run_cli(["Production", "Read", "-r", "x"])
    assert code == 1
    assert out == [
        FETCH_SUBS,
        _fetch_roles(1),
        "Activating 2 role(s)…",
        "  • Reader  —  s1… ✗",
        "  • Key Vault Reader  —  s1… ✓ Provisioned",
    ]
    assert err == ["    ERROR: (Boom) Reader failed"]
    assert fake_azure.activations == [
        ("Reader", "/subscriptions/s1", "PT1H", False),
        ("Key Vault Reader", "/subscriptions/s1", "PT1H", False),
    ]


def test_S13_subscription_list_fails(run_cli, fake_azure) -> None:
    fake_azure.subs_err = "az exploded"
    code, out, err = run_cli(["Production", "Reader", "-r", "x"])
    assert code == 1
    assert out == [FETCH_SUBS]
    assert err == ["Error fetching subscriptions: az exploded"]
    assert fake_azure.activations == []


def test_S14_role_fetch_fails_for_one_sub(run_cli, fake_azure) -> None:
    fake_azure.roles_err_sub = "s1"
    code, out, err = run_cli(["Contoso", "Reader", "-r", "x"])
    assert code == 0
    assert out == [
        FETCH_SUBS,
        _fetch_roles(2),
        "Activating 1 role(s)…",
        "  • Reader  —  s2… ✓ Provisioned",
    ]
    assert err == [
        "Warning: failed to fetch roles for 'Contoso Production': role fetch failed for s1",
    ]
    assert fake_azure.activations == [("Reader", "/subscriptions/s2", "PT1H", False)]


def test_S15_demo_with_reason_uses_real_path(run_cli, fake_azure) -> None:
    """--demo is ignored with -r: the real Azure path runs, not dry-run.

    Characterizes current behaviour; see F41/F45.
    """
    code, out, err = run_cli(["--demo", "Production", "Key Vault Reader", "-r", "x"])
    assert code == 0
    assert out == [
        FETCH_SUBS,
        _fetch_roles(1),
        "Activating 1 role(s)…",
        "  • Key Vault Reader  —  s1… ✓ Provisioned",
    ]
    assert err == []
    assert fake_azure.calls == [("list_subscriptions",), ("list_eligible_roles", "s1")]
    assert fake_azure.activations == [("Key Vault Reader", "/subscriptions/s1", "PT1H", False)]


def test_S16_empty_reason_is_accepted(run_cli, fake_azure) -> None:
    """An empty -r is passed through as the justification.

    Characterizes current behaviour; see F41/F45.
    """
    code, out, err = run_cli(["Production", "Key Vault Reader", "-r", ""])
    assert code == 0
    assert out == [
        FETCH_SUBS,
        _fetch_roles(1),
        "Activating 1 role(s)…",
        "  • Key Vault Reader  —  s1… ✓ Provisioned",
    ]
    assert err == []
    assert fake_azure.activations == [("Key Vault Reader", "/subscriptions/s1", "PT1H", False)]
    assert fake_azure.justifications == [""]


# ---------------------------------------------------------------------------
# Management group mode (--mg)
# ---------------------------------------------------------------------------


def test_M1_success(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["--mg", "Corp", "Reader", "-r", "x"])
    assert code == 0
    assert out == [
        FETCH_MGS,
        _fetch_mg_roles("Corp"),
        "Activating 1 role(s)…",
        "  • Reader  —  corp… ✓ Provisioned",
    ]
    assert err == []
    assert fake_azure.calls == [("list_management_groups",), ("list_eligible_roles_mg", "corp")]
    assert fake_azure.activations == [("Reader", MG_CORP, "PT1H", False)]


def test_M2_display_name_matches_several_groups(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["--mg", "Platform", "Reader", "-r", "x"])
    assert code == 1
    assert out == [FETCH_MGS]
    assert err == [
        "Error: 'Platform' matches multiple management groups — be more specific:",
        "  Platform  (platform)",
        "  Platform Dev  (platform-dev)",
    ]
    assert fake_azure.activations == []


def test_M3_exact_id_that_is_also_a_substring_is_ambiguous(run_cli, fake_azure) -> None:
    """An exact MG id does not win over substring matches of other groups.

    Characterizes current behaviour; see F43.
    """
    code, out, err = run_cli(["--mg", "platform", "Reader", "-r", "x"])
    assert code == 1
    assert out == [FETCH_MGS]
    assert err == [
        "Error: 'platform' matches multiple management groups — be more specific:",
        "  Platform  (platform)",
        "  Platform Dev  (platform-dev)",
    ]
    assert fake_azure.activations == []


def test_M4_no_group_match(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["--mg", "nope", "Reader", "-r", "x"])
    assert code == 1
    assert out == [FETCH_MGS]
    assert err == [
        "Error: No management group matching 'nope' found.",
        "Available management groups:",
        "  Platform  (platform)",
        "  Platform Dev  (platform-dev)",
        "  Corp  (corp)",
    ]
    assert fake_azure.activations == []


def test_M5_no_role_match(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["--mg", "Corp", "Nope", "-r", "x"])
    assert code == 1
    assert out == [FETCH_MGS, _fetch_mg_roles("Corp")]
    assert err == [
        "Error: No eligible role matching 'Nope' found.",
        "Available eligible roles:",
        "  Owner",
        "  Reader",
    ]
    assert fake_azure.activations == []


def test_M6_no_roles(run_cli, fake_azure) -> None:
    fake_azure.mg_roles = {}
    code, out, err = run_cli(["--mg", "Corp", "Reader", "-r", "x"])
    assert code == 1
    assert out == [FETCH_MGS, _fetch_mg_roles("Corp")]
    assert err == ["Error: No eligible PIM roles found."]
    assert fake_azure.activations == []


def test_M7_inherited_parent_mg_role_is_activated(run_cli, fake_azure) -> None:
    """--mg keeps roles inherited from parent MGs and activates them there.

    Characterizes current behaviour; see F42.
    """
    code, out, err = run_cli(["--mg", "Corp", "Owner", "-r", "x"])
    assert code == 0
    assert out == [
        FETCH_MGS,
        _fetch_mg_roles("Corp"),
        "Activating 1 role(s)…",
        "  • Owner  —  Tenant Root… ✓ Provisioned",
    ]
    assert err == []
    assert fake_azure.activations == [("Owner", ROOT_MG, "PT1H", False)]


def test_M8_all_matches_already_active(run_cli, fake_azure) -> None:
    fake_azure.mg_roles = {"corp": [role("Reader", MG_CORP, active=True)]}
    code, out, err = run_cli(["--mg", "Corp", "Reader", "-r", "x"])
    assert code == 0
    assert out == [
        FETCH_MGS,
        _fetch_mg_roles("Corp"),
        "All 1 matching role(s) are already active.",
    ]
    assert err == []
    assert fake_azure.activations == []


def test_M8_some_matches_already_active(run_cli, fake_azure) -> None:
    fake_azure.mg_roles = {
        "corp": [role("Reader", MG_CORP, active=True), role("Key Vault Reader", MG_CORP)]
    }
    code, out, err = run_cli(["--mg", "Corp", "Read", "-r", "x"])
    assert code == 0
    assert out == [
        FETCH_MGS,
        _fetch_mg_roles("Corp"),
        "Skipping 1 already-active role(s).",
        "Activating 1 role(s)…",
        "  • Key Vault Reader  —  corp… ✓ Provisioned",
    ]
    assert err == []
    assert fake_azure.activations == [("Key Vault Reader", MG_CORP, "PT1H", False)]


def test_M9_partial_failure(run_cli, fake_azure) -> None:
    fake_azure.fail_on = {"Reader"}
    code, out, err = run_cli(["--mg", "Corp", "r", "-r", "x"])
    assert code == 1
    assert out == [
        FETCH_MGS,
        _fetch_mg_roles("Corp"),
        "Activating 2 role(s)…",
        "  • Reader  —  corp… ✗",
        "  • Owner  —  Tenant Root… ✓ Provisioned",
    ]
    assert err == ["    ERROR: (Boom) Reader failed"]
    assert fake_azure.activations == [
        ("Reader", MG_CORP, "PT1H", False),
        ("Owner", ROOT_MG, "PT1H", False),
    ]


def test_M10_group_list_fails(run_cli, fake_azure) -> None:
    fake_azure.mg_err = "az exploded"
    code, out, err = run_cli(["--mg", "Corp", "Reader", "-r", "x"])
    assert code == 1
    assert out == [FETCH_MGS]
    assert err == ["Error fetching management groups: az exploded"]
    assert fake_azure.activations == []


def test_M11_role_fetch_fails(run_cli, fake_azure) -> None:
    fake_azure.mg_roles_err = "forbidden"
    code, out, err = run_cli(["--mg", "Corp", "Reader", "-r", "x"])
    assert code == 1
    assert out == [FETCH_MGS, _fetch_mg_roles("Corp")]
    assert err == ["Error fetching roles: forbidden"]
    assert fake_azure.activations == []


# ---------------------------------------------------------------------------
# Entra mode (--entra)
# ---------------------------------------------------------------------------


def test_E1_success_with_device_code(run_cli, fake_azure) -> None:
    fake_azure.device_code = True
    code, out, err = run_cli(["--entra", "Global Reader", "-r", "x", "-t", "2h"])
    assert code == 0
    assert out == [
        FETCH_ENTRA,
        "",
        "Sign in to Microsoft Graph:",
        "  1. Open:       https://microsoft.com/devicelogin",
        "  2. Enter code: ABCD-1234",
        "",
        "Activating 1 Entra role(s)…",
        "  • Global Reader… ✓ Provisioned",
    ]
    assert err == []
    assert fake_azure.activations == [("Global Reader", "/", "PT2H", False)]


def test_E2_substring_with_some_active(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["--entra", "Reader", "-r", "x"])
    assert code == 0
    assert out == [
        FETCH_ENTRA,
        "Skipping 1 already-active role(s).",
        "Activating 2 Entra role(s)…",
        "  • Global Reader… ✓ Provisioned",
        "  • Security Reader… ✓ Provisioned",
    ]
    assert err == []
    assert fake_azure.activations == [
        ("Global Reader", "/", "PT1H", False),
        ("Security Reader", "/", "PT1H", False),
    ]


def test_E3_all_matches_already_active(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["--entra", "reports reader", "-r", "x"])
    assert code == 0
    assert out == [FETCH_ENTRA, "All 1 matching role(s) are already active."]
    assert err == []
    assert fake_azure.activations == []


def test_E4_no_role_match(run_cli, fake_azure) -> None:
    code, out, err = run_cli(["--entra", "Nope", "-r", "x"])
    assert code == 1
    assert out == [FETCH_ENTRA]
    assert err == [
        "Error: No eligible Entra role matching 'Nope' found.",
        "Available eligible Entra roles:",
        "  Global Reader",
        "  Reports Reader",
        "  Security Reader",
    ]
    assert fake_azure.activations == []


def test_E5_no_roles(run_cli, fake_azure) -> None:
    fake_azure.entra = []
    code, out, err = run_cli(["--entra", "Reader", "-r", "x"])
    assert code == 1
    assert out == [FETCH_ENTRA]
    assert err == ["Error: No eligible Entra PIM roles found."]
    assert fake_azure.activations == []


def test_E6_partial_failure(run_cli, fake_azure) -> None:
    fake_azure.fail_on = {"Global Reader"}
    code, out, err = run_cli(["--entra", "Reader", "-r", "x"])
    assert code == 1
    assert out == [
        FETCH_ENTRA,
        "Skipping 1 already-active role(s).",
        "Activating 2 Entra role(s)…",
        "  • Global Reader… ✗",
        "  • Security Reader… ✓ Provisioned",
    ]
    assert err == ["    Graph says no"]
    assert fake_azure.activations == [
        ("Global Reader", "/", "PT1H", False),
        ("Security Reader", "/", "PT1H", False),
    ]


def test_E7_runtime_error(run_cli, fake_azure) -> None:
    fake_azure.entra_err = "token expired"
    code, out, err = run_cli(["--entra", "Reader", "-r", "x"])
    assert code == 1
    assert out == [FETCH_ENTRA]
    assert err == ["Error fetching Entra roles: token expired"]
    assert fake_azure.activations == []
