"""Entry point for fzf-pim."""

from __future__ import annotations

import argparse
import logging
import sys


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser (used by argparse-manpage at build time)."""
    parser = argparse.ArgumentParser(
        prog="fzf-pim",
        description="TUI for activating Azure PIM eligible roles with multiselect.",
        epilog=(
            "Authentication is fully delegated to the active 'az' CLI session. "
            "Run 'az login' before using this tool.\n\n"
            "Non-interactive (CLI-only) activation:\n"
            "  Azure RBAC:  fzf-pim SUBSCRIPTION ROLE -r REASON [-t DURATION]\n"
            "  Mgmt group:  fzf-pim --mg MG ROLE -r REASON [-t DURATION]\n"
            "  Entra ID:    fzf-pim --entra ROLE -r REASON [-t DURATION]\n\n"
            "Examples:\n"
            '  fzf-pim my-sub "Key Vault Administrator" -r "Break-glass" -t 30m\n'
            '  fzf-pim --mg my-mg "Reader" -r "Audit review" -t 1h\n'
            '  fzf-pim --entra "Global Reader" -r "Audit review" -t 1h'
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
        "-r", "--reason",
        metavar="TEXT",
        default=None,
        help="Justification for activation (enables non-interactive mode).",
    )
    parser.add_argument(
        "-t", "--time",
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
        "--log",
        metavar="FILE",
        default=None,
        help="Write verbose debug logs to FILE (e.g. --log /tmp/fzf-pim.log).",
    )
    return parser


def _cli_activate(
    subscription: str,
    role_name: str,
    justification: str,
    duration: str,
    dry_run: bool = False,
) -> None:
    """Non-interactive activation: find matching eligible roles and activate them."""
    from fzf_pim import azure

    try:
        iso_duration = azure.parse_duration(duration)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Fetching subscriptions…")
    try:
        subs = azure.list_subscriptions()
    except Exception as exc:
        print(f"Error fetching subscriptions: {exc}", file=sys.stderr)
        sys.exit(1)

    sub_lower = subscription.lower()
    filtered = [
        s for s in subs
        if sub_lower in s.name.lower() or sub_lower == s.id.lower()
    ]
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

    if not all_roles:
        print("Error: No eligible PIM roles found.", file=sys.stderr)
        sys.exit(1)

    role_lower = role_name.lower()
    exact = [r for r in all_roles if r.role_name.lower() == role_lower]
    matching = exact or [r for r in all_roles if role_lower in r.role_name.lower()]

    if not matching:
        print(f"Error: No eligible role matching '{role_name}' found.", file=sys.stderr)
        print("Available eligible roles:", file=sys.stderr)
        for name in sorted({r.role_name for r in all_roles}):
            print(f"  {name}", file=sys.stderr)
        sys.exit(1)

    inactive = [r for r in matching if not r.is_active]
    if not inactive:
        print(f"All {len(matching)} matching role(s) are already active.")
        return
    if len(inactive) < len(matching):
        skipped = len(matching) - len(inactive)
        print(f"Skipping {skipped} already-active role(s).")
    matching = inactive

    print(f"Activating {len(matching)} role(s)…")
    errors = 0
    for role in matching:
        print(f"  • {role.role_name}  —  {role.scope_display_name}… ", end="", flush=True)
        try:
            result = azure.activate_role(role, justification, iso_duration, dry_run=dry_run)
            status = result.get("properties", {}).get("status", "Submitted")
            print(f"✓ {status}")
        except Exception as exc:
            print(f"✗")
            print(f"    {exc}", file=sys.stderr)
            errors += 1

    if errors:
        sys.exit(1)


def _cli_activate_mg(
    management_group: str,
    role_name: str,
    justification: str,
    duration: str,
    dry_run: bool = False,
) -> None:
    """Non-interactive activation scoped to a management group."""
    from fzf_pim import azure

    try:
        iso_duration = azure.parse_duration(duration)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    print("Fetching management groups…")
    try:
        mgs = azure.list_management_groups()
    except Exception as exc:
        print(f"Error fetching management groups: {exc}", file=sys.stderr)
        sys.exit(1)

    mg_lower = management_group.lower()
    filtered = [
        mg for mg in mgs
        if mg_lower in mg.name.lower() or mg_lower == mg.id.lower()
    ]
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

    if not all_roles:
        print("Error: No eligible PIM roles found.", file=sys.stderr)
        sys.exit(1)

    role_lower = role_name.lower()
    exact = [r for r in all_roles if r.role_name.lower() == role_lower]
    matching = exact or [r for r in all_roles if role_lower in r.role_name.lower()]

    if not matching:
        print(f"Error: No eligible role matching '{role_name}' found.", file=sys.stderr)
        print("Available eligible roles:", file=sys.stderr)
        for name in sorted({r.role_name for r in all_roles}):
            print(f"  {name}", file=sys.stderr)
        sys.exit(1)

    inactive = [r for r in matching if not r.is_active]
    if not inactive:
        print(f"All {len(matching)} matching role(s) are already active.")
        return
    if len(inactive) < len(matching):
        skipped = len(matching) - len(inactive)
        print(f"Skipping {skipped} already-active role(s).")
    matching = inactive

    print(f"Activating {len(matching)} role(s)…")
    errors = 0
    for role in matching:
        print(f"  • {role.role_name}  —  {role.scope_display_name}… ", end="", flush=True)
        try:
            result = azure.activate_role(role, justification, iso_duration, dry_run=dry_run)
            status = result.get("properties", {}).get("status", "Submitted")
            print(f"✓ {status}")
        except Exception as exc:
            print("✗")
            print(f"    {exc}", file=sys.stderr)
            errors += 1

    if errors:
        sys.exit(1)


def _cli_activate_entra(
    role_name: str,
    justification: str,
    duration: str,
    dry_run: bool = False,
) -> None:
    """Non-interactive Entra activation: find matching eligible roles and activate them."""
    from fzf_pim import azure

    try:
        iso_duration = azure.parse_duration(duration)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

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

    if not all_roles:
        print("Error: No eligible Entra PIM roles found.", file=sys.stderr)
        sys.exit(1)

    role_lower = role_name.lower()
    exact = [r for r in all_roles if r.role_name.lower() == role_lower]
    matching = exact or [r for r in all_roles if role_lower in r.role_name.lower()]

    if not matching:
        print(f"Error: No eligible Entra role matching '{role_name}' found.", file=sys.stderr)
        print("Available eligible Entra roles:", file=sys.stderr)
        for name in sorted({r.role_name for r in all_roles}):
            print(f"  {name}", file=sys.stderr)
        sys.exit(1)

    inactive = [r for r in matching if not r.is_active]
    if not inactive:
        print(f"All {len(matching)} matching role(s) are already active.")
        return
    if len(inactive) < len(matching):
        skipped = len(matching) - len(inactive)
        print(f"Skipping {skipped} already-active role(s).")
    matching = inactive

    print(f"Activating {len(matching)} Entra role(s)…")
    errors = 0
    for role in matching:
        print(f"  • {role.role_name}… ", end="", flush=True)
        try:
            result = azure.activate_entra_role(role, justification, iso_duration, dry_run=dry_run)
            status = result.get("status", "Submitted")
            print(f"✓ {status}")
        except Exception as exc:
            print("✗")
            print(f"    {exc}", file=sys.stderr)
            errors += 1

    if errors:
        sys.exit(1)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.log:
        logging.basicConfig(
            filename=args.log,
            level=logging.DEBUG,
            format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    else:
        logging.disable(logging.CRITICAL)

    positional: list[str] = args.positional

    if args.reason is not None:
        if args.entra:
            if len(positional) != 1:
                parser.error(
                    "Provide exactly one positional argument (ROLE) when using --entra --reason/-r"
                )
            _cli_activate_entra(
                role_name=positional[0],
                justification=args.reason,
                duration=args.duration,
                dry_run=args.dry_run,
            )
            return
        if args.mg:
            if len(positional) != 1:
                parser.error(
                    "Provide exactly one positional argument (ROLE) when using --mg --reason/-r"
                )
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
            parser.error(
                "Provide SUBSCRIPTION ROLE as positional arguments when using --reason/-r"
            )
        _cli_activate(
            subscription=subscription,
            role_name=role_name,
            justification=args.reason,
            duration=args.duration,
            dry_run=args.dry_run,
        )
        return

    if positional:
        parser.error(
            "Positional arguments require --reason/-r for non-interactive activation"
        )

    from fzf_pim.app import PimApp

    PimApp(dry_run=args.dry_run, entra=args.entra).run()


if __name__ == "__main__":
    main()
