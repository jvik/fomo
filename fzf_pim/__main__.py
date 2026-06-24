"""Entry point for fzf-pim."""

from __future__ import annotations

import argparse
import logging

from fzf_pim.app import PimApp


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="fzf-pim",
        description="TUI for activating Azure PIM eligible roles with multiselect.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate activation without calling the Azure API.",
    )
    parser.add_argument(
        "--log",
        metavar="FILE",
        default=None,
        help="Write verbose debug logs to FILE (e.g. --log /tmp/fzf-pim.log).",
    )
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

    PimApp(dry_run=args.dry_run).run()


if __name__ == "__main__":
    main()
