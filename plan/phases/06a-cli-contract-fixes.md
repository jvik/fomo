# Phase 06a: fix(cli)!, contract changes for currently broken cases (opt-in per item)

**Group:** 6. Runs only if uncommented in QUEUE.
**Decisions:** `OPT_6A_*` (only items set to `yes` run), and D10.

Each item changes CLI output **only** in a situation that today fails, hangs or targets the wrong thing. They're still contract changes, so each one ships as its **own commit**:
- with D10 = `yes`: type `fix(cli)!:` or `fix!:` plus a `BREAKING CHANGE:` footer that states the exact old and new behaviour
- with D10 = `no`: plain `fix(cli):`, with the same footer text under a `Contract-Change:` trailer

## Rules for touching `tests/test_cli_contract.py`

You may edit **only** the rows that the item's commit says it changes. For each, update the expectation and put `# changed by <item> (F##)` above it.

Never delete a row. For a row whose behaviour stops existing, convert it to assert the new behaviour. Add new rows for new cases, named `test_6a_<item>_<case>`. List the touched row IDs in the commit body.

## Items

| Decision | Finding | Change | Rows affected |
|---|---|---|---|
| `OPT_6A_PAGINATION` | F11 | Add a `_paged(url)` helper in azure.py that follows `nextLink` (ARM, via `az rest`) and `@odata.nextLink` (Graph, via `_run_graph`). Use it for every list call | None of S/M/E change with the single-page fakes. Add `test_6a_pagination_*` with a 2-page fake at the `_run_az`/`_run_graph` boundary |
| `OPT_6A_TENANT` | F05 | `_get_graph_token` compares the cached `tenant_id` with `_get_tenant_id()`. On mismatch it skips the refresh token, runs the device-code flow and caches per tenant (`graph_token.json` becomes `{tenant_id: {...}}`, migrating the old format). The in-process cache is keyed by tenant | Add tests. E rows are unchanged because they fake `list_entra_eligible_roles` |
| `OPT_6A_TIMEOUTS` | F12 | Default timeouts: 120 s for `az`, 30 s for HTTP, 15 s for tiering (already). A timeout raises `RuntimeError("az <subcommand> timed out after 120s")`. The existing `Error fetching …: <msg>` paths print it | Add a test for each mode. If 05's `--timeout` exists, it overrides the default |
| `OPT_6A_ENTRA_SCOPE` | F18 | Entra `is_active` keyed by `(roleDefinitionId, directoryScopeId)` | E2/E3 are unchanged (the fakes set `is_active` directly). Add an azure-level test |
| `OPT_6A_MG_EXACT` | F43 | MG matching: an exact (case-insensitive) match on ID or display name wins before substring ambiguity | M3 changes from exit 1 (ambiguous) to exit 0 (activates `platform`) |
| `OPT_6A_DURATION` | F44 | `parse_duration` accepts lowercase ISO (`pt1h` → `PT1H`) and rejects zero durations (`0m`, `PT0M`, `PT0H`) with the existing error format: `Error: Invalid duration '0m'. Use e.g. …` (exit 1) | Add rows. Existing U8 is unchanged |
| `OPT_6A_CTRL_C` | F47 | `main()` catches `KeyboardInterrupt` in CLI mode, prints `Interrupted.` to stderr and exits 130 | U12 changes from "propagates" to exit 130 with stderr `Interrupted.` |

## Docs

README and the man page get one line per behaviour change. If D10 is `yes`, note in the README that this release bumps the major version and why.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- Every changed contract row has its `# changed by` comment and is listed in a commit body.
- Lint and the type checker are clean.

## Commits

One per approved item, for example:

```
fix(cli)!: an exact management group ID now wins over substring matches

BREAKING CHANGE: `fomo --mg platform ...` used to fail with "matches multiple
management groups" when other groups' names contained "platform"; it now
selects the group whose ID or name is exactly "platform". Contract row M3 changed.
```

Tick `06a`, and record in STATUS "Notes" which items ran.
