# Phase 02d: docs, align README, man page and AGENTS.md with the code

**Group:** 2
**Findings:** F29 · REPORT.md §3, rows 1–9, 11, 13–15, 17
**Contract:** none. **Don't edit `build_parser()` help or epilog text**; that's phase 05 (D9).

The code is the source of truth: document what it does today. Where a later phase changes behaviour, that phase updates the docs it affects.

## Steps

### 1. README.md

- **Row 1:** matching. "An exact role name (case-insensitive) wins. Otherwise every role whose name contains the text is activated. Subscriptions match by name substring or exact ID, and every matching subscription is used."
- **Row 2:** say activations are submitted one after another, not in parallel.
- **Row 3:** ARM calls use the `az` session. Entra roles use a separate Microsoft Graph device-code sign-in whose refresh token is cached in `~/.cache/fomo/graph_token.json`. To sign in again, delete that file.
- **Row 13:** the device code comes back when the refresh token expires.
- **Row 11:** `--demo` affects only the TUI. Combined with `-r` it is ignored today (see F41). Add a warning sentence.
- **Row 17:** management-group activation is CLI-only (`--mg`).
- **New "Network access" note:** blast-radius tier data is downloaded from the public `emiliensocchi/azure-tiering` GitHub repo and cached for 7 days in `~/.cache/fomo/`.
- Keep README:92 (`l` switches tabs) as it is; 04a makes it true.

### 2. `man/fomo.1.include`

- **Row 2:** remove the "submitted in parallel" sentence.
- **Row 3:** rewrite "never handles credentials or tokens directly" to describe the Graph device-code flow and the token cache.
- **Row 5:** remove "Up to 3 roles may be selected"; say more than 3 triggers a warning.
- **Row 6:**
  - Subscription screen: `a` all, `n` none, `/` filter, Escape toggles between filter and list, `x`/Space toggles, `i` assignments, `h`/`l` switch tabs, `q` quit.
  - Roles: Tab and Shift+Tab move between filter and list, `a` selects all visible, Ctrl-s sorts, Escape/`q` go back.
  - Remove the non-existent Ctrl-a entries.
- **Row 9:**
  - Add an Entra tab subsection (`--entra` opens on it, device-code sign-in).
  - Add an Assignments screen subsection (`i`; `1`–`4` sort; Escape/`q` back).
  - Add an Entra activation subsection.
- **Row 7:** fix EXAMPLES. Use `.EX` / `.EE` blocks, or `.nf` / `.fi` with `\(dq` for embedded double quotes, so every example renders in full (for example `fomo my-sub "Key Vault Administrator" -r "Break-glass access" -t 1h`).
- **Row 8:** replace the bogus `AZURE_CLI` ENVIRONMENT entry. Describe `PATH` (`az` must be on it) and `HOME` / `~/.cache/fomo` (token and tiering caches) under FILES or ENVIRONMENT.
- Keep the existing section names (`[=DESCRIPTION]`, `[WORKFLOW]`, `[KEY BINDINGS]`, `[EXAMPLES]`, `[ENVIRONMENT]`, `[SEE ALSO]`), which argparse-manpage's include format requires. A `[FILES]` section is allowed.

### 3. AGENTS.md

- **Row 14:** complete the layout: `tiering.py`, `widgets.py`, `demo.py`, `backend.py` (from 02c), `screens/entra_screen.py`, `screens/assignments_screen.py`, `screens/_activation_base.py`, `screens/_common.py`, `hatch_build.py`, `scripts/screenshot.py`, `man/fomo.1.include`, `tests/`.
- **Row 4:** add an explicit exception to the transport rule: "Microsoft Graph (Entra PIM) and the OAuth token endpoint are called with stdlib `urllib`, because `az`'s first-party app lacks the PIM Graph scope. Tier data is fetched with `urllib` from GitHub. Don't add other HTTP code."
- Add a "CLI contract" section:
  - `tests/test_cli_contract.py` is frozen.
  - `__main__.py` keeps stdlib-only top-level imports (hatch hook).
  - Behaviour changes need an explicit breaking-change commit.
- Replace "uv run pytest (if present)" with the real commands, including lint and type checking if 02a added them.

### 4. Docstring and PR template

- **Row 15:** fix the `list_eligible_roles` docstring in `fomo/azure.py`. Already-active roles are included with `is_active=True`.
- `.github/PULL_REQUEST_TEMPLATE.md`: add checkboxes for "CLI contract tests unchanged (or breaking change declared)", "Tried in `--demo` / `--dry-run`" and "Docs/man page updated if behaviour changed".

## Verify

- `.venv/bin/python -m pytest -q` passes.
- Render the include as a check. The runner also checks the built man page after you finish: `MANWIDTH=140 man -l man/fomo.1 | grep 'Break-glass access'` must match. That text appears only in the EXAMPLES section, so a truncated example fails the check.
- You can't run `uv build`. Instead, sanity-check the roff by rendering a throwaway copy, `man -l plan/logs/scratch/check.1`, built from a minimal `.TH` header plus your sections with the `[SECTION]` lines turned into `.SH SECTION`.

## Commits

- `docs: align README with actual matching, auth and network behaviour`
- `docs(man): fix examples rendering and document all screens and keys`
- `docs: update AGENTS.md layout, transport exception and CLI contract rules`
- `docs: fix list_eligible_roles docstring and PR template`

Tick `02d`.
