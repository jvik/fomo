"""Hatchling build hook — generates the fomo.1 man page at build time."""

from __future__ import annotations

import importlib.util
import os

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    PLUGIN_NAME = "custom"

    def initialize(self, version: str, build_data: dict) -> None:
        from argparse_manpage.manpage import Manpage
        from argparse_manpage.tooling import write_to_filename

        # Load __main__ by exact file path so we always use the local source
        # tree regardless of what may be installed elsewhere on sys.path.
        main_path = os.path.join(self.root, "fomo", "__main__.py")
        spec = importlib.util.spec_from_file_location("fomo.__main__", main_path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load module from {main_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        # Build a fresh parser and clear the brief description so it doesn't
        # appear as a duplicate alongside the richer [=DESCRIPTION] include
        # block.  We own this object — it is never used for --help output.
        parser = module.build_parser()
        parser.description = None

        include_file = os.path.join(self.root, "man", "fomo.1.include")
        if not os.path.isfile(include_file):
            raise FileNotFoundError(
                f"Man page include file not found: {include_file}"
            )

        manpage = Manpage(
            parser,
            format="pretty",
            _data={
                "project_name": "fomo",
                "url": "https://github.com/jvik/fomo",
                "description": "TUI for activating Azure PIM eligible roles with multiselect",
                "authors": None,
                "long_description": None,
                "prog": "fomo",
                "version": version,
                "manual_section": None,
                "manual_title": None,
                "include": include_file,
                "manfile": None,
            },
        )

        man_dir = os.path.join(self.root, "man")
        os.makedirs(man_dir, exist_ok=True)
        out_file = os.path.join(man_dir, "fomo.1")
        write_to_filename(str(manpage), out_file)

        build_data.setdefault("shared_data", {})["man/fomo.1"] = (
            "share/man/man1/fomo.1"
        )
