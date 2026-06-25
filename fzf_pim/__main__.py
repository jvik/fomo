"""Entry point for fzf-pim."""

from __future__ import annotations

import argparse
import logging


def build_parser() -> argparse.ArgumentParser:
    """Return the argument parser (used by argparse-manpage at build time)."""
    parser = argparse.ArgumentParser(
        prog="fzf-pim",
        description="TUI for activating Azure PIM eligible roles with multiselect.",
        epilog=(
            "Authentication is fully delegated to the active 'az' CLI session. "
            "Run 'az login' before using this tool."
        ),
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

    from fzf_pim.app import PimApp

    PimApp(dry_run=args.dry_run, entra=args.entra).run()


if __name__ == "__main__":
    main()
