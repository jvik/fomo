# Phase 01: test, CLI characterization and Pilot smoke tests

**Group:** 1
**Findings:** F28 · REPORT.md §1
**Contract:** this phase *defines* the contract tests
**Don't touch:** anything under `fomo/`

## Goal

Pin today's CLI behaviour (exit code, stdout, stderr) for every row in REPORT.md §1, and add one Pilot smoke test per screen. These tests **characterize** what the code does, including the odd parts. Never "fix" an expectation to match the docs.

## Steps

### 1. `tests/conftest.py`: hermetic by default (autouse)

- **Kill switch.** Monkeypatch `subprocess.run`, `urllib.request.urlopen` and `webbrowser.open` to raise `AssertionError("real I/O in tests: …")`. Patch the module attributes, `subprocess.run` and `urllib.request.urlopen`, so every importer is covered.
- Point `fomo.azure._TOKEN_CACHE_PATH` at `tmp_path / "graph_token.json"`, and set `fomo.azure._graph_token_cache = None`.
- Point `fomo.tiering._CACHE_DIR` at `tmp_path`, reset `_azure_index` and `_entra_index` to `{}`, and make `fomo.tiering._fetch_json` return `None`. A `tiering_fixture` fixture can opt in to small fixture data.
- In teardown call `logging.disable(logging.NOTSET)`, because `main()` calls `logging.disable(CRITICAL)` globally.

### 2. `fake_azure` fixture

Monkeypatch these functions on `fomo.azure` with in-memory fakes:
- `list_subscriptions`, `list_eligible_roles`, `list_management_groups`, `list_eligible_roles_mg`, `list_entra_eligible_roles`
- `activate_role`, `activate_entra_role`
- `check_auth`, `get_account_info`, `list_active_arm_assignments`, `list_active_entra_assignments`

The fake records every activation as `(role_name, scope_or_dir_scope, duration, dry_run)`. It supports failure toggles:
- `subs_err`, `mg_err` and `entra_err`
- `roles_err_sub` (one sub's role fetch raises)
- `fail_on={role names}` (activation raises `RuntimeError("ERROR: (Boom) <name> failed")` for ARM, and `RuntimeError("Graph says no")` for Entra)
- `device_code=True` (the Entra fake calls `on_device_code("https://microsoft.com/devicelogin\nABCD-1234")`)

Use exactly this data, because REPORT.md §1 was captured with it:

```python
SUBS = [Subscription("s1", "Contoso Production"), Subscription("s2", "Contoso Dev")]
MGS = [ManagementGroup("platform", "Platform"), ManagementGroup("platform-dev", "Platform Dev"),
       ManagementGroup("corp", "Corp")]
def role(name, scope, active=False, disp=None):
    return EligibleRole(name, f"{scope}/providers/x/roleDefinitions/{name}", scope,
                        disp or scope.rsplit("/", 1)[-1], "u", "sched", None, active)
ROLES = {
    "s1": [role("Reader", "/subscriptions/s1"), role("Key Vault Reader", "/subscriptions/s1"),
           role("Contributor", "/subscriptions/s1", active=True),
           role("Reader", "/providers/Microsoft.Management/managementGroups/root", disp="Tenant Root")],
    "s2": [role("Reader", "/subscriptions/s2")],
}
MG_ROLES = {"corp": [role("Reader", "/providers/Microsoft.Management/managementGroups/corp"),
                     role("Owner", "/providers/Microsoft.Management/managementGroups/root", disp="Tenant Root")]}
ENTRA = [EntraEligibleRole("Global Reader", "gr", "u", "e1", None),
         EntraEligibleRole("Security Reader", "sr", "u", "e2", None),
         EntraEligibleRole("Reports Reader", "rr", "u", "e3", None, is_active=True)]
```

Successful fakes return `{"properties": {"status": "DryRun" if dry_run else "Provisioned"}}` for ARM, and `{"status": …}` for Entra.

### 3. `run_cli(argv)` helper

Set `sys.argv`, call `fomo.__main__.main()`, catch `SystemExit` (`None` means 0), and use `capsys` to return `(code, stdout_lines, stderr_lines)`.

### 4. `tests/test_cli_contract.py`

One test per row in REPORT.md §1: U1–U12, S1–S16, M1–M11, E1–E7.

**Characterize first.** For each row, run the invocation against the fakes and capture the output. Confirm it matches REPORT.md (it should), then assert it.

Assert in every test:
- the exact exit code
- **full** stdout lines and **full** stderr lines, compared as lists
- the recorded activations (which roles, which scopes, duration, `dry_run`)

For usage errors (exit 2), assert:
- the exit code
- that stdout is empty
- that the **last** stderr line is exactly the `fomo: error: …` text

Don't assert the `usage:` lines here; they go in a separate file, below.

Specific rows:
- **U8:** for each mode, assert that no fetch function was called.
- **U9:** assert, via `build_parser()._actions`:
  - each option's `option_strings`, `dest`, `default` and `metavar`
  - `prog == "fomo"`
  - positional `nargs == "*"` and `metavar == "ARG"`
- **U11:** load `fomo/__main__.py` with `importlib.util.spec_from_file_location("fomo.__main__", path)`, temporarily setting `sys.modules["fomo"] = None` and `sys.modules["textual"] = None`. Assert that `module.build_parser().parse_args([])` works.
- **U12:** the fake `list_subscriptions` raises `KeyboardInterrupt`. Assert that it propagates out of `main()` (`pytest.raises(KeyboardInterrupt)`).
- **S15 and S16:** document current behaviour. Their docstrings must say "characterizes current behaviour; see F41/F45".
- **M3 and M7:** same, with docstrings citing F43 and F42.

Name each test after its row ID, for example `test_S6_no_subscription_match`, so later phases can cite rows.

### 5. `tests/test_cli_usage_snapshot.py`

Assert the exact `usage:` block that argparse prints for U1, and the first line of `-h` output. This is the one place phase 05 may deliberately update (see DECISIONS.md, D4).

### 6. `tests/test_tui_smoke.py`

Use `App.run_test()` inside `asyncio.run()` in plain sync tests, so no pytest-asyncio is needed.

- `make_app(**kw)` helper:
  - monkeypatch `fomo.app._system_is_dark` to return `True`
  - set `PimApp._watch_color_scheme = lambda self: None`
  - use `demo_mode=True, dry_run=True` unless the test says otherwise
- Write a `wait_for(pilot, cond, timeout=3)` polling helper.

Tests:
- **Scope:** `#sub-list` has 5 options. Pressing `l` from the tab bar activates `tab-entra`, and `#entra-role-list` gets 5 options.
- **Roles:** select subs 0–2 (pause before Enter), press Enter, and `#role-list` loads. The active role "Contributor" option is disabled. `ctrl+s` cycles `_sort_mode` through name → scope → tier → expiry.
- **Activation:** select the first non-active role, press Enter, and type a justification. Press `#btn-activate` and wait until `#btn-back` shows "Done". Every status cell contains `DryRun`.
- **Entra activation:** the same flow from the Entra tab.
- **Assignments:** `i` from the sub list, then `#azure-table` has 4 rows and `#entra-table` has 2 rows. Escape returns to `ScopeScreen`.
- **AuthErrorModal:** with `demo_mode=False`, `fake_azure`, and `check_auth` raising `RuntimeError("AADSTS700082: … Please run 'az login'")`, the modal is on top. Pressing `q` exits the app.

### 7. Optional snapshots (D3)

If `DECISIONS.md` has `D3_SNAPSHOT_TESTS=yes`, add `pytest-textual-snapshot` snapshots for the five screens at 80x24. The runner has already installed the dependency. Commit the `pyproject.toml` change it made, in the `test(tui)` commit.

### 8. Rename a misleading test

In `tests/test_cli.py`, rename `test_parser_cli_mode_role_only` to `test_parser_accepts_single_positional_at_parse_level`. Its docstring should say that `main()` rejects this invocation (U1).

## Verify

- `.venv/bin/python -m pytest -q` passes.
- The whole suite runs in under 30 s.
- Grep the new tests to confirm none calls real `az` or the network. The kill switch would raise.

## Commits

- `test: add hermetic fixtures and fake azure boundary`
- `test(cli): characterize the non-interactive CLI contract`
- `test(tui): add Pilot smoke tests for every screen`

The last commit also ticks `01` in plan/STATUS.md.
