# Phase 03b: fix(tui), tiering data can never break role loading

**Group:** 3
**Findings:** F02, F19 (pin and fallback), F40 (no network in demo)
**Contract:** none. The CLI doesn't use tiering.
**Decision:** D5

**Runner pre-step:** if D5 is `pin-sha`, the current `main` SHA of `emiliensocchi/azure-tiering` is in `plan/logs/tiering-sha.txt`. The file is empty if the lookup failed.

## Problem (verified)

- `RolesScreen._load_roles_for_sub` runs `tiering.load_azure()` and the UI callback inside the same `try` as the role fetch. One malformed upstream entry (`{"id": null}` makes `None.lower()` raise) turns into the subscription's error, and the result is "No eligible PIM roles found."
- An exception inside the UI callback runs `_increment_loaded` twice ("Loading roles… 2/1").
- `_save_disk_cache` calls `os.makedirs` outside its `try`, so an unwritable `~/.cache` also breaks role loading.
- `ScopeScreen._load_entra_roles` has the same pattern for Entra.

## Steps

### 1. `fomo/tiering.py`

- `_build_index` skips any entry that isn't a dict, whose `id` isn't a non-empty str, or whose `tier` isn't int-convertible. Log one debug line per skipped entry.
- Cache directory: `os.makedirs(..., exist_ok=True)` inside the `try`. Write atomically to a temp file in the same directory, then `os.replace`.
- Stale fallback: split the disk cache into fresh and stale. If the fetch fails, use stale data rather than nothing, and log at info level.
- `ensure_azure_loaded()` and `ensure_entra_loaded()` (added in 02c; add them now if 02c was skipped) **never raise**. Catch `Exception`, log a warning, and leave the index empty.
- Add an `allow_network: bool = True` parameter. Demo mode passes `False`, so demo uses only the cache, or nothing.
- **Pinning (D5 = `pin-sha` and a 40-hex SHA in `plan/logs/tiering-sha.txt`):** replace `main` in `_AZURE_URL` and `_ENTRA_URL` with a module constant `_TIERING_REF = "<sha>"`, and comment how to bump it. If there's no SHA, keep `main` and add a line to STATUS "Notes".

### 2. Screens

- `roles_screen.py`: wrap **only** the fetch in `try`/`except`, and post the success or error callback outside it.
  - Load tiering in a separate guarded step: `tiering.ensure_azure_loaded(allow_network=not demo)`, called once before or after the fetches. When tiering finishes after the list renders, refresh the detail pane.
  - `_loaded_count` increments exactly once per subscription.
- `scope_screen.py` (Entra): the same separation.

### 3. Docs

Add a README sentence: tier data is pinned to a specific upstream commit, or refreshed weekly if it isn't pinned. Stale data is used offline, and demo mode makes no network calls.

## Tests

- `_build_index` with a malformed mix (`None`, `{"id": None}`, `{"id": "x", "tier": "a"}` and a valid entry) keeps only the valid entry.
- `_fetch_json` returning `[{"id": None, "tier": 1}]` with no cache: the roles screen still lists the roles, and the detail pane says no tiering data.
- An unwritable cache dir (`tiering._CACHE_DIR` pointing below a file): roles still load.
- Stale cache: the file's mtime is older than the TTL and the fetch fails, so the index comes from the stale file.
- `load_*` with `allow_network=False` never calls `_fetch_json` (the fake asserts this).
- The loading label never exceeds N/N. Assert `_loaded_count == len(subs)` after a forced callback exception, by monkeypatching `_rebuild_list` to raise once.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- Lint and the type checker are clean.

## Commits

- `fix(tui): never let tiering data break role loading`
- `fix(tiering): skip malformed entries, write the cache atomically, fall back to stale data`
- `chore(tiering): pin upstream tier data to a commit` (only if pinned)

Tick `03b`.
