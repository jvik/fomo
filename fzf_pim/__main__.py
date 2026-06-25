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
            "  fzf-pim ROLE -r REASON [-t DURATION]\n"
            "  fzf-pim SUBSCRIPTION ROLE -r REASON [-t DURATION]\n\n"
            "Examples:\n"
            '  fzf-pim "Key Vault Administrator" -r "Break-glass" -t 1h\n'
            '  fzf-pim my-sub "Key Vault Administrator" -r "Break-glass" -t 30m'
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "positional",
        nargs="*",
        metavar="ARG",
        help=(
            "When --reason/-r is also given: directly activate a role without the TUI. "
            "Provide one argument (ROLE) or two (SUBSCRIPTION ROLE). "
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
        help="Start in Microsoft Entra PIM mode (Entra ID roles instead of Azure RBAC).",
    )
    parser.add_argument(
        "--log",
        metavar="FILE",
        default=None,
        help="Write verbose debug logs to FILE (e.g. --log /tmp/fzf-pim.log).",
    )
    return parser


def _cli_activate(
    subscription: str | None,
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

    if subscription:
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
        if len(positional) == 1:
            subscription = None
            role_name = positional[0]
        elif len(positional) == 2:
            subscription = positional[0]
            role_name = positional[1]
        else:
            parser.error(
                "Provide [SUBSCRIPTION] ROLE as positional argument(s) when using --reason/-r"
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
