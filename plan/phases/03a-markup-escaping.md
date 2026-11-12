# Phase 03a: fix(tui), render external text literally (markup escaping)

**Group:** 3
**Findings:** F01
**Contract:** none. The CLI doesn't use markup.

## Problem (verified)

External strings are interpolated into Textual markup unescaped:
- A subscription named `Broken [/] sub` raises `MarkupError` in `ScopeScreen._rebuild_list`. The worker's `except` passes that message to `_show_error`, which raises again on the same text, and the worker fails, exiting the app at startup.
- Tiering text `Assign roles at [/subscriptions/*] scope` crashes `RolesScreen._update_detail`.
- `Plain [bold]sub[/bold] name [legacy]` renders as "Plain sub name", and `Team [red] sandbox` as "Team  sandbox".

## Steps

### 1. Add one helper

Add the helper in `fomo/screens/_common.py`, or `fomo/markup.py` if `_common` doesn't exist.
- Check the installed Textual first: `textual.markup.escape` and/or `Content.from_markup(template, **variables)`, where `$var` substitution is escaped automatically. Prefer `Content.from_markup` with variables where it reads cleanly; otherwise escape.
- Write a unit test proving `"[/]"`, `"[bold]x[/bold]"`, `"[legacy]"` and `"\\"` all render literally, by comparing `.plain` text.

### 2. Route every external string through it

`git grep -n` for `.update(f"`, `add_option(`, `Selection(`, `notify(f"`, `Label(f"`, `Text.from_markup(f"`, `RichLog.write`, `add_row(` and `update_cell_at`. External strings include:
- subscription names and IDs
- role names
- scope display names
- expiry text
- every `str(exc)` and Azure or Graph error message
- tiering `attack_path` and `name`
- the device-code URL and code
- account user and tenant in the title

Places to cover:
- `scope_screen.py`: `_rebuild_list`, `_show_error`, `_rebuild_entra_list`, `_update_entra_detail`, `_on_entra_error`, and the device-code label.
- `roles_screen.py`: `_rebuild_list` (including the `[expires …]` tag), `_update_detail`, and the notify in `_on_roles_error`.
- Activation screens: `DataTable` cells. Check whether Textual 8 parses `str` cells as markup; if it does, pass `Text(value)` or `Content(value)`. `RichLog(markup=True).write(message)` must write the error message as plain text, keeping the red markup only on the role-name header line.
- `assignments_screen.py`: table rows and error labels.
- `app.py`: the title (plain attribute, probably safe; check) and the AuthErrorModal body if it ever includes external text.
- `tiering.high_risk_summary`, which goes into `notify`.

### 3. Toasts

Check `App.notify(..., markup=...)` in the installed Textual. Pass `markup=False`, or escape, for messages with external text.

## Tests

Add them to `tests/test_tui_markup.py`. Use the fake azure fixture and `demo_mode=False`, `dry_run=True`.
- Subs named `Broken [/] sub`, `Plain [bold]sub[/bold] name [legacy]` and `Team [red] sandbox`: the app doesn't crash, and the rendered text of `#sub-list` contains the names verbatim.
- A role named `Key Vault Administrator [preview]` with scope `rg-[x]` and tier text containing `[/subscriptions/*]`: the roles screen loads and the detail pane shows all three verbatim.
- `list_subscriptions` raising `RuntimeError("bad [/] thing")` shows the error label with the text verbatim; no crash.
- Activation failing with `RuntimeError("ERROR: [/x] (Boom)")` puts the text verbatim in the RichLog and the status cell.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- Lint and the type checker are clean.

## Commit

`fix(tui): render Azure names, errors and tier text literally`

The body cites the crash on `[/]` names. Tick `03a`.
