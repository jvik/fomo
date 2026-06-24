"""Hatchling build hook — generates the fzf-pim.1 man page at build time."""

from __future__ import annotations

import os
import sys

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        # Ensure the local source tree is importable when argparse-manpage
        # loads fzf_pim.__main__ to introspect the ArgumentParser.
        if self.root not in sys.path:
            sys.path.insert(0, self.root)

        from argparse_manpage.manpage import Manpage
        from argparse_manpage.tooling import get_parser, write_to_filename

        parser = get_parser(
            "module",
            "fzf_pim.__main__",
            "build_parser",
            "function",
            prog="fzf-pim",
        )
        # The include file supplies a richer [=DESCRIPTION]; clear the brief
        # argparse description so it doesn't get appended as a duplicate.
        # The running app's --help is unaffected (get_parser returns a fresh object).
        parser.description = None

        include_file = os.path.join(self.root, "man", "fzf-pim.1.include")

        manpage = Manpage(
            parser,
            format="pretty",
            _data={
                "project_name": "fzf-pim",
                "url": "https://github.com/mfyll/fzf-pim",
                "description": "TUI for activating Azure PIM eligible roles with multiselect",
                "authors": None,
                "long_description": None,
                "prog": "fzf-pim",
                "version": version,
                "manual_section": None,
                "manual_title": None,
                "include": include_file,
                "manfile": None,
            },
        )

        man_dir = os.path.join(self.root, "man")
        os.makedirs(man_dir, exist_ok=True)
        out_file = os.path.join(man_dir, "fzf-pim.1")
        write_to_filename(str(manpage), out_file)

        build_data.setdefault("shared_data", {})["man/fzf-pim.1"] = (
            "share/man/man1/fzf-pim.1"
        )
