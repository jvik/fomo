"""Entry point for fomo."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, NoReturn, Protocol, TypeVar

if TYPE_CHECKING:
    from fomo import azure


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser (used by argparse-manpage at build time)."""
    parser = argparse.ArgumentParser(
        prog="fomo",
        description="TUI for activating Azure PIM eligible roles with multiselect.",
        epilog=(
            "Authentication is fully delegated to the active 'az' CLI session. "
            "Run 'az login' before using this tool.\n\n"
            "Non-interactive (CLI-only) activation:\n"
            "  Azure RBAC:  fomo SUBSCRIPTION ROLE -r REASON [-t DURATION]\n"
            "  Mgmt group:  fomo --mg MG ROLE -r REASON [-t DURATION]\n"
            "  Entra ID:    fomo --entra ROLE -r REASON [-t DURATION]\n\n"
            "Examples:\n"
            '  fomo my-sub "Key Vault Administrator" -r "Break-glass" -t 30m\n'
            '  fomo --mg my-mg "Reader" -r "Audit review" -t 1h\n'
            '  fomo --entra "Global Reader" -r "Audit review" -t 1h'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "positional",
        nargs="*",
        metavar="ARG",
        help=(
            "When --reason/-r is also given: directly activate a role without the TUI. "
            "Azure RBAC: provide two arguments (SUBSCRIPTION ROLE). "
            "Management group (--mg): provide one argument (ROLE). "
            "Entra ID (--entra): provide one argument (ROLE). "
            "SUBSCRIPTION may be a name substring or full ID."
        ),
    )
    parser.add_argument(
        "-r",
        "--reason",
        metavar="TEXT",
        default=None,
        help="Justification for activation (enables non-interactive mode).",
    )
    parser.add_argument(
        "-t",
        "--time",
        metavar="DURATION",
        dest="duration",
        default="PT1H",
        help="Activation duration (e.g. 30m, 1h, PT1H). Default: PT1H.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate activation without calling the Azure API.",
    )
    parser.add_argument(
        "--entra",
        action="store_true",
        help=(
            "Activate Microsoft Entra ID roles instead of Azure RBAC. "
            "Can be combined with -r/--reason for non-interactive mode."
        ),
    )
    parser.add_argument(
        "--mg",
        metavar="MANAGEMENT_GROUP",
        default=None,
        help=(
            "Activate roles scoped to a management group instead of a subscription. "
            "Provide the management group name (substring match) or full ID. "
            "Requires -r/--reason for non-interactive mode."
        ),
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Launch with dummy data — no Azure auth required (for screenshots).",
    )
    parser.add_argument(
        "--log",
        metavar="FILE",
        default=None,
        help="Write verbose debug logs to FILE (e.g. --log /tmp/fomo.log).",
    )
    return parser


class _Role(Protocol):
    """What the shared CLI helpers need from an eligible ARM or Entra role."""

    @property
    def role_name(self) -> str: ...

    @property
    def is_active(self) -> bool: ...


_R = TypeVar("_R", bound=_Role)


def _parse_duration_or_exit(duration: str) -> str:
    """Return *duration* as ISO 8601, or print the error and exit 1."""
    from fomo import azure

    try:
        return azure.parse_duration(duration)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)


def _match_roles(all_roles: Sequence[_R], role_name: str) -> list[_R]:
    """Exact (case-insensitive) role-name matches, otherwise substring matches."""
    role_lower = role_name.lower()
    exact = [r for r in all_roles if r.role_name.lower() == role_lower]
    return exact or [r for r in all_roles if role_lower in r.role_name.lower()]


def _exit_no_role_match(role_name: str, all_roles: Sequence[_Role], *, entra: bool) -> NoReturn:
    """Print the per-mode no-match error and the available role names, then exit 1."""
    kind = "Entra role" if entra else "role"
    print(f"Error: No eligible {kind} matching '{role_name}' found.", file=sys.stderr)
    print(f"Available eligible {kind}s:", file=sys.stderr)
    for name in sorted({r.role_name for r in all_roles}):
        print(f"  {name}", file=sys.stderr)
    sys.exit(1)


def _drop_active(matching: list[_R]) -> list[_R] | None:
    """Return the inactive roles, or None (after saying so) if all are already active."""
    inactive = [r for r in matching if not r.is_active]
    if not inactive:
        print(f"All {len(matching)} matching role(s) are already active.")
        return None
    if len(inactive) < len(matching):
        skipped = len(matching) - len(inactive)
        print(f"Skipping {skipped} already-active role(s).")
    return inactive


def _select_roles(all_roles: Sequence[_R], role_name: str, *, entra: bool) -> list[_R] | None:
    """Match *role_name* against *all_roles* and drop already-active roles.

    Exits 1 if there are no eligible roles or nothing matches; returns None if
    every matching role is already active.
    """
    if not all_roles:
        kind = "Entra PIM" if entra else "PIM"
        print(f"Error: No eligible {kind} roles found.", file=sys.stderr)
        sys.exit(1)

    matching = _match_roles(all_roles, role_name)
    if not matching:
        _exit_no_role_match(role_name, all_roles, entra=entra)
    return _drop_active(matching)


def _activate_all(
    roles: Sequence[_R],
    activate: Callable[..., dict],
    *,
    header: str,
    line_for: Callable[[_R], str],
    status_of: Callable[[dict], Any],
    duration: str,
    justification: str,
    dry_run: bool,
) -> int:
    """Activate *roles* in order, printing one progress line each; return the error count."""
    print(header)
    errors = 0
    for role in roles:
        print(f"  • {line_for(role)}… ", end="", flush=True)
        try:
            result = activate(role, justification, duration, dry_run=dry_run)
            print(f"✓ {status_of(result)}")
        except Exception as exc:
            print("✗")
            print(f"    {exc}", file=sys.stderr)
            errors += 1
    return errors


def _activate_arm_roles(
    roles: Sequence[azure.EligibleRole],
    justification: str,
    iso_duration: str,
    dry_run: bool,
) -> None:
    """Activate ARM roles (subscription or management-group mode); exit 1 on any failure."""
    from fomo import azure

    errors = _activate_all(
        roles,
        azure.activate_role,
        header=f"Activating {len(roles)} role(s)…",
        line_for=lambda r: f"{r.role_name}  —  {r.scope_display_name}",
        status_of=lambda result: result.get("properties", {}).get("status", "Submitted"),
        duration=iso_duration,
        justification=justification,
        dry_run=dry_run,
    )
    if errors:
        sys.exit(1)


def _cli_activate(
    subscription: str,
    role_name: str,
    justification: str,
    duration: str,
    dry_run: bool = False,
) -> None:
    """Non-interactive activation: find matching eligible roles and activate them."""
    from fomo import azure

    iso_duration = _parse_duration_or_exit(duration)

    print("Fetching subscriptions…")
    try:
        subs = azure.list_subscriptions()
    except Exception as exc:
        print(f"Error fetching subscriptions: {exc}", file=sys.stderr)
        sys.exit(1)

    sub_lower = subscription.lower()
    filtered = [s for s in subs if sub_lower in s.name.lower() or sub_lower == s.id.lower()]
    if not filtered:
        print(f"Error: No subscription matching '{subscription}' found.", file=sys.stderr)
        print("Available subscriptions:", file=sys.stderr)
        for s in subs:
            print(f"  {s.name}  ({s.id})", file=sys.stderr)
        sys.exit(1)
    subs = filtered

    print(f"Fetching eligible roles from {len(subs)} subscription(s)…")
    all_roles: list[azure.EligibleRole] = []
    for sub in subs:
        try:
            roles = azure.list_eligible_roles(sub.id)
            all_roles.extend(roles)
        except Exception as exc:
            print(f"Warning: failed to fetch roles for '{sub.name}': {exc}", file=sys.stderr)

    # Drop roles inherited from parent management groups — their actual scope
    # is outside the requested subscription and activating them affects broader scopes.
    sub_prefixes = tuple(f"/subscriptions/{s.id}" for s in subs)
    all_roles = [r for r in all_roles if r.scope.startswith(sub_prefixes)]

    matching = _select_roles(all_roles, role_name, entra=False)
    if matching is None:
        return
    _activate_arm_roles(matching, justification, iso_duration, dry_run)


def _cli_activate_mg(
    management_group: str,
    role_name: str,
    justification: str,
    duration: str,
    dry_run: bool = False,
) -> None:
    """Non-interactive activation scoped to a management group."""
    from fomo import azure

    iso_duration = _parse_duration_or_exit(duration)

    print("Fetching management groups…")
    try:
        mgs = azure.list_management_groups()
    except Exception as exc:
        print(f"Error fetching management groups: {exc}", file=sys.stderr)
        sys.exit(1)

    mg_lower = management_group.lower()
    filtered = [mg for mg in mgs if mg_lower in mg.name.lower() or mg_lower == mg.id.lower()]
    if not filtered:
        print(f"Error: No management group matching '{management_group}' found.", file=sys.stderr)
        print("Available management groups:", file=sys.stderr)
        for mg in mgs:
            print(f"  {mg.name}  ({mg.id})", file=sys.stderr)
        sys.exit(1)
    if len(filtered) > 1:
        print(
            f"Error: '{management_group}' matches multiple management groups — be more specific:",
            file=sys.stderr,
        )
        for mg in filtered:
            print(f"  {mg.name}  ({mg.id})", file=sys.stderr)
        sys.exit(1)
    mg = filtered[0]

    print(f"Fetching eligible roles for management group '{mg.name}'…")
    try:
        all_roles = azure.list_eligible_roles_mg(mg.id)
    except Exception as exc:
        print(f"Error fetching roles: {exc}", file=sys.stderr)
        sys.exit(1)

    # Unlike subscription mode, roles inherited from parent management groups
    # are kept here (current contract).
    matching = _select_roles(all_roles, role_name, entra=False)
    if matching is None:
        return
    _activate_arm_roles(matching, justification, iso_duration, dry_run)


def _cli_activate_entra(
    role_name: str,
    justification: str,
    duration: str,
    dry_run: bool = False,
) -> None:
    """Non-interactive Entra activation: find matching eligible roles and activate them."""
    from fomo import azure

    iso_duration = _parse_duration_or_exit(duration)

    def _on_device_code(message: str) -> None:
        url, _, code = message.partition("\n")
        print()
        print("Sign in to Microsoft Graph:")
        print(f"  1. Open:       {url}")
        print(f"  2. Enter code: {code}")
        print()

    print("Fetching Entra eligible roles…")
    try:
        all_roles = azure.list_entra_eligible_roles(on_device_code=_on_device_code)
    except Exception as exc:
        print(f"Error fetching Entra roles: {exc}", file=sys.stderr)
        sys.exit(1)

    matching = _select_roles(all_roles, role_name, entra=True)
    if matching is None:
        return

    errors = _activate_all(
        matching,
        azure.activate_entra_role,
        header=f"Activating {len(matching)} Entra role(s)…",
        line_for=lambda r: r.role_name,
        status_of=lambda result: result.get("status", "Submitted"),
        duration=iso_duration,
        justification=justification,
        dry_run=dry_run,
    )
    if errors:
        sys.exit(1)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.log:
        from fomo.state import make_fd_private

        # The log holds account details: create a new file private (0600), and
        # make a reused one private too (older versions left it readable by
        # others).  Checked and changed through the descriptor, so both see
        # the file being logged to; a terminal or pipe is left alone.
        fd = os.open(args.log, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            make_fd_private(fd)
        finally:
            os.close(fd)
        logging.basicConfig(
            filename=args.log,
            level=logging.DEBUG,
            format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    else:
        logging.disable(logging.CRITICAL)

    from fomo import azure

    # Older versions wrote the Graph token cache readable by others.
    azure.make_token_cache_private()

    positional: list[str] = args.positional

    if args.entra and args.mg:
        parser.error("--entra and --mg are mutually exclusive")

    if args.mg and args.reason is None:
        parser.error("--mg requires -r/--reason for non-interactive activation")

    if args.reason is not None:
        if args.entra:
            if len(positional) != 1:
                parser.error("Provide exactly one positional argument (ROLE) when using --entra --reason/-r")
            _cli_activate_entra(
                role_name=positional[0],
                justification=args.reason,
                duration=args.duration,
                dry_run=args.dry_run,
            )
            return
        if args.mg:
            if len(positional) != 1:
                parser.error("Provide exactly one positional argument (ROLE) when using --mg --reason/-r")
            _cli_activate_mg(
                management_group=args.mg,
                role_name=positional[0],
                justification=args.reason,
                duration=args.duration,
                dry_run=args.dry_run,
            )
            return
        if len(positional) == 2:
            subscription = positional[0]
            role_name = positional[1]
        else:
            parser.error("Provide SUBSCRIPTION ROLE as positional arguments when using --reason/-r")
        _cli_activate(
            subscription=subscription,
            role_name=role_name,
            justification=args.reason,
            duration=args.duration,
            dry_run=args.dry_run,
        )
        return

    if positional:
        parser.error("Positional arguments require --reason/-r for non-interactive activation")

    from fomo.app import PimApp

    PimApp(dry_run=args.dry_run, entra=args.entra, demo_mode=args.demo).run()


if __name__ == "__main__":
    main()
