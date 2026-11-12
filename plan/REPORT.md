# fomo audit report (2026-11-07)

## Summary

The codebase is small and readable, and the happy path works. Demo mode is good for screenshots. The safety net is thin, though:
- The 16 existing tests are all parse-level, so nothing pins the CLI contract today.
- Several paths crash or mislead when real-world data shows up.
- The docs have drifted from the code.

Baseline: `uv run pytest` gives **16 passed**. `uv build` builds the sdist and wheel, and the wheel ships `share/man/man1/fomo.1`. Runs used Textual 8.2.8 and Python 3.12.15.

**Top 3 priorities**
1. **Pin the CLI contract first.** Characterization tests (phase 01) need to exist before any refactor. Today there are zero tests of `_cli_activate*`.
2. **Crash and robustness bugs from external text.** Subscription names, Azure error text and the third-party tiering JSON all go into Textual markup unescaped. A subscription named `x [/] y` crashes fomo at startup, and one malformed tiering entry makes every role "not found" (F01, F02).
3. **Security hygiene.** `--log` writes a live ARM bearer token and the user's profile to a 0644 file. The Graph refresh-token cache is briefly world-readable, and it's reused across tenants (F03–F05).

Two CLI behaviours are safety-relevant but would change the contract, so they're opt-in (06b):
- `--demo` is silently ignored with `-r`, so the activation is real.
- `--mg` activates roles inherited from *parent* management groups.

---

## 1. Characterization matrix (phase 01)

Every row was observed by running the CLI in-process against fakes at the `fomo.azure` boundary. Wording is verbatim. The fake data used is defined in `phases/01-characterization.md`.

**Existing coverage:** `tests/test_cli.py` covers `parse_duration` (8 tests) and argparse parsing (7 tests). None of the rows below existed before phase 01, except U9, which was partly covered.

**Usage errors and common flags (all modes)**

| ID | Invocation | Exit | Asserts |
|---|---|---|---|
| U1 | `fomo Reader -r x` | 2 | stderr ends `fomo: error: Provide SUBSCRIPTION ROLE as positional arguments when using --reason/-r` |
| U2 | `fomo a b c -r x` | 2 | same as U1 |
| U3 | `fomo Reader` | 2 | `…Positional arguments require --reason/-r for non-interactive activation` |
| U4 | `fomo --entra --mg m R -r x` | 2 | `…--entra and --mg are mutually exclusive` |
| U5 | `fomo --mg m R` | 2 | `…--mg requires -r/--reason for non-interactive activation` |
| U6 / U7 | `--entra a b -r x` / `--mg m a b -r x` | 2 | `…Provide exactly one positional argument (ROLE) when using --entra --reason/-r` (or `--mg`) |
| U8 | each mode with `-t 90` | 1 | stdout empty; stderr `Error: Invalid duration '90'. Use e.g. '30m', '1h', '1h30m', or ISO 8601 like 'PT1H'.`; no fetch calls |
| U9 | `build_parser()` | – | every flag in short and long form, `dest`, default (`PT1H`, `None`), metavar; `-h` exits 0 |
| U10 | each mode with `--dry-run` | 0 | `dry_run=True` passed through; line ends `✓ DryRun` |
| U11 | load `fomo/__main__.py` standalone, the way `hatch_build.py:20-25` does, with `fomo.*` and `textual` blocked | – | `build_parser()` still works |
| U12 | Ctrl+C (fake raises `KeyboardInterrupt`) | – | `KeyboardInterrupt` propagates out of `main()` |

**Subscription mode**

| ID | Situation | Exit | stdout | stderr |
|---|---|---|---|---|
| S1 | success | 0 | `Fetching subscriptions…` / `Fetching eligible roles from 1 subscription(s)…` / `Activating 1 role(s)…` / `  • Key Vault Reader  —  s1… ✓ Provisioned` | empty |
| S2 | an exact name beats a substring, across 2 subs | 0 | activates `Reader` in **both** subs and skips `Key Vault Reader` | |
| S3, S4, S5 | case-insensitive exact match; substring that matches several roles (activates **all**); exact subscription ID | 0 | | |
| S6 | no subscription matches | 1 | `Fetching subscriptions…` | `Error: No subscription matching 'nomatch' found.` / `Available subscriptions:` / `  Contoso Production  (s1)` … |
| S7 | no role matches | 1 | | `Error: No eligible role matching 'Owner' found.` / `Available eligible roles:` / sorted unique names |
| S8 | no roles left after filtering | 1 | | `Error: No eligible PIM roles found.` |
| S9 | role inherited from a parent MG | – | filtered out: neither listed nor activated | |
| S10 / S11 | all matches active / some active | 0 | `All 1 matching role(s) are already active.` / `Skipping 1 already-active role(s).` | |
| S12 | partial failure | 1 | `  • Reader  —  s1… ✗` (the other roles are still attempted) | `    ERROR: (…)` |
| S13 | subscription list fails | 1 | | `Error fetching subscriptions: <msg>` |
| S14 | role fetch fails for one sub | 0 | other subs still activate | `Warning: failed to fetch roles for 'Contoso Production': <msg>` |
| S15 | `--demo … -r x` *(as-is)* | 0 | real Azure path is used | |
| S16 | `-r ""` *(as-is)* | 0 | accepted | |

**Management group mode (`--mg`)**

| ID | Situation | Exit | Key lines |
|---|---|---|---|
| M1 | success | 0 | stdout `Fetching management groups…` / `Fetching eligible roles for management group 'Corp'…` / `Activating 1 role(s)…` / `  • Reader  —  corp… ✓ Provisioned` |
| M2 | display name matches several groups | 1 | stderr `Error: 'Platform' matches multiple management groups — be more specific:` / `  Platform  (platform)` … |
| M3 | exact ID that's also a substring of another name *(as-is)* | 1 | same ambiguity error |
| M4 | no group matches | 1 | stderr `Error: No management group matching 'nope' found.` / `Available management groups:` … |
| M5 / M6 | no role matches / no roles | 1 | `Error: No eligible role matching 'Nope' found.` / `Error: No eligible PIM roles found.` |
| M7 | role inherited from a parent MG *(as-is)* | 0 | **activated** at the parent scope: `  • Owner  —  Tenant Root… ✓ Provisioned` |
| M8–M11 | already active / partial failure / group list error / role fetch error | 0/1/1/1 | `Error fetching management groups: …`, `Error fetching roles: …` |

**Entra mode (`--entra`)**

| ID | Situation | Exit | Key lines |
|---|---|---|---|
| E1 | success with a device-code prompt | 0 | stdout: blank / `Sign in to Microsoft Graph:` / `  1. Open:       <url>` / `  2. Enter code: <code>` / blank / `Activating 1 Entra role(s)…` / `  • Global Reader… ✓ Provisioned` |
| E2 / E3 | substring match with some active / all active | 0 | `Skipping 1 already-active role(s).` / `All 1 matching role(s) are already active.` |
| E4 / E5 | no match / no roles | 1 | `Error: No eligible Entra role matching 'Nope' found.` + `Available eligible Entra roles:` / `Error: No eligible Entra PIM roles found.` |
| E6 / E7 | partial failure / runtime error | 1 | stderr `    <msg>` / `Error fetching Entra roles: <msg>` |

**Pilot smoke test for each screen.** These run in demo mode with theme detection, the dbus watcher and the tiering fetch stubbed.
- Scope: 5 subs load, and the Entra tab lazy-loads.
- Roles: the active role is disabled, and the sort cycles.
- Activation: every row shows `✓ DryRun` and the button reads `Done`.
- Entra activation: the same.
- Assignments: both tables are populated.
- AuthErrorModal: Quit exits the app.

---

## 2. Findings

"Verified" means reproduced headless. "CLI" says whether the fix touches the CLI contract; `6a` and `6b` are the opt-in phases.

| ID | Area | file:line | Issue | Impact | Proposed fix | Effort | Risk | CLI |
|---|---|---|---|---|---|---|---|---|
| F01 | A | scope_screen.py:183,200,397-423 · roles_screen.py:108,177-180,233-257 · assignments_screen.py:115 · activation RichLog/DataTable | External strings (sub, role and scope names, Azure errors, tiering text) go into markup unescaped | **Verified:** a sub named `x [/] y` crashes at startup (the error path re-raises, then WorkerFailed). Tier text `[/subscriptions/*]` crashes the roles screen. `[legacy]` and `[red]` silently vanish from names | Escape every external string, or build `Content`/`Text` objects | S | low | n |
| F02 | A | roles_screen.py:82-93 · scope_screen.py:259-282 · tiering.py:80,99-120 | The tiering load sits inside the role-fetch `try`, as do the UI callbacks | **Verified:** one malformed upstream entry leads to "No eligible PIM roles found". UI exceptions are counted twice ("Loading roles… 2/1") | Guard tiering separately and skip bad entries. Move `makedirs` inside the `try`. Wrap only the fetch | S | low | n |
| F03 | A | azure.py:36,56,212 · app.py:217 · __main__.py:349-355 | `--log` logs the stdout of every `az` call, including `account get-access-token` and `ad signed-in-user show` | **Verified:** the ARM bearer token and the user's profile (phone) go into a 0644 log | `check_auth` uses `--query expiresOn`. Redact token keys, skip profile bodies, open the log 0600 | S | low | n |
| F04 | A | azure.py:436-448 | The token file is created with the default umask, then chmod'd. The directory is 0755. Symlinks are followed | **Verified:** the file is 0644 while the refresh token is written | `makedirs(mode=0o700)`, `os.open(…, 0o600 \| O_NOFOLLOW)` and an atomic replace | S | low | n |
| F05 | A | azure.py:562,567-571 | The Graph refresh uses the *cached* tenant, and the in-process token isn't keyed by tenant | **Verified:** after `az login --tenant B`, the token is refreshed for tenant A while the principal ID comes from B | Compare with the current `az` tenant, key caches by tenant, fall back to device code | S | low | 6a |
| F06 | A | activation_screen.py:70-74,130 · entra_screen.py:66,103 | `Select` allows a blank value, which yields a truthy `Select.NULL` | **Verified:** `Select.NULL` reaches `activate_role`. A real run fails with a JSON serialization error | `allow_blank=False` | S | low | n |
| F07 | C | activation_screen.py:48-79 · entra_screen.py:54-71 · app.tcss:49-52,124-168 | Non-scrolling `Vertical`, a 36-column Status column, and a RichLog that doesn't wrap | **Verified:** at 80x24 with 5 roles the Duration field isn't rendered. After an error the whole form disappears. At 120x36 Duration collapses. Errors are cut off | `VerticalScroll`, form first, cap the table height, `RichLog(wrap=True)`, flexible Status column | M | low | n |
| F08 | C | scope_screen.py:125-131 | `h`/`l` hide the focused list, focus jumps to the old pane's filter, and `TabbedContent._on_tab_pane_focused` switches back | **Verified:** the tab only switches from the tab bar. The next `i`/`a`/`q` is typed into the filter | Focus the target pane (or the tab bar) before switching | S | low | n |
| F09 | C | scope_screen.py:443-447,480-486 · roles_screen.py:319-320,355-357 | Focusing a list from the filter leaves `highlighted=None` | **Verified:** the first Space does nothing | Set `highlighted=0` when it's `None` on focus | S | low | n |
| F10 | C | activation_screen.py:198-211 · entra_screen.py:150-163 | "Done" returns to Roles with the role still selected and not marked active. Activate stays disabled. No quit, retry or assignments option | Re-submitting leads to RoleAssignmentExists errors. Failed roles can't be retried | A post-activation action bar, clear the selection, refresh active state | M | low | n |
| F11 | A | azure.py:249,286,320,717 · 621,642,753 | `nextLink` / `@odata.nextLink` are never followed | Silent truncation for large tenants | A `_paged()` helper | S | low | 6a |
| F12 | A | azure.py:38,465,490,524,599 | No timeout on any `subprocess.run` or `urlopen` | Scripts hang forever and TUI workers freeze | Timeouts that raise `RuntimeError` | S | low | 6a |
| F13 | A | azure.py:499-504,526-528 | The device-code flow always calls `webbrowser.open`, crashes on a non-JSON body, and blocks the CLI for up to 15 minutes | **Verified:** `JSONDecodeError` on a 502 HTML body | Open a browser only when a display exists, tolerate non-JSON bodies | S | low | n |
| F14 | A | azure.py:547-587 | `_get_graph_token` isn't locked. The Entra tab and Assignments can each start a device-code flow | Two codes, two browser tabs | A lock around token acquisition | S | low | n |
| F15 | A/C | azure.py:60-73 · roles_screen.py:102-106 · app.py:62-65,222 | `is_auth_error` matches any `aadsts`/`please run`. The modal text is clipped and there's no Retry | **Verified:** MFA (AADSTS50076) is shown as "session expired… restart", and the modal drops "fomo." | Classify specific codes, show the raw message, wrap the label, add Retry | S | low | n |
| F16 | A | roles_screen.py:73-74 · azure.py:318-320 | One thread per selected sub, each running 3 `az` processes | 50 subs means about 150 concurrent `az` processes | Cache the user ID, bounded pool of 4 | S | low | n |
| F17 | A | azure.py:285-288,620-623 | Active-state lookups swallow every error | Active roles look inactive, the CLI exits 1 instead of reporting "already active" | Log a warning (behaviour unchanged) | S | low | n |
| F18 | A | azure.py:657 | Entra `is_active` ignores `directoryScopeId` | An AU-scoped activation marks the tenant-wide eligibility active | Key by role definition plus scope | S | low | 6a |
| F19 | A | tiering.py:22-29,67-76,89-96 | Tier data is fetched at runtime from an unpinned third-party `main` branch, even in `--demo`. A stale cache is discarded if the fetch fails | A third party controls the risk labels shown before privileged activation | Pin a SHA, keep stale cache as fallback, no network in demo, document the call | M | low | n |
| F20 | A | scope_screen.py:310-315 | The wrap slices `msg[i:i+80]` instead of `line` | **Verified:** the first line is duplicated and the end of the long line is lost | Fix the slice and share the helper | S | low | n |
| F21 | A | app.py:265 | `parts[1]` is read when the line is just `uint32` | `IndexError` in a worker exits the app (rare) | Length check | S | low | n |
| F22 | B | __main__.py:91-342 | Three near-identical `_cli_activate*` functions | Drift already happened: MG mode lacks the inherited-role filter | Shared helpers with byte-identical output | M | med | n |
| F23 | B | entra_screen.py ≈ activation_screen.py · scope_screen.py:248-431 ≈ roles_screen.py · vim actions ×3 · device-code callback ×2 · `demo_mode` checks ×6 · screens read `tiering._azure_index` | Duplication and scattered demo branching | Fixes land in one copy only (F20 is an example) | Shared activation base and list pane, a `Backend`, `tiering.ensure_loaded()` | M-L | med | n |
| F24 | B | pyproject.toml:11 · widgets.py:10-11 · scope_screen.py:24 · roles_screen.py:12 · .gitignore:28 | `textual>=0.70.0` (the Theme API arrived around 0.86; only 8.2.8 verified), private `textual.widgets._*` imports, `uv.lock` ignored | Untested or broken resolutions | `textual>=8.2,<9`, public imports, commit `uv.lock` | S | low | n |
| F25 | B | fomo/_version.py · .gitignore:37 | The generated version file is tracked (stale `1.13.2.dev0`). The ignore rule still says `fzf_pim/` | Every sync or build dirties the tree | Untrack and ignore it | S | low | n |
| F26 | B | repo | No lint, format or type checking. Examples: unused `Text` (scope_screen.py:26), unused `log` (assignments_screen.py:17), imports after constants (roles_screen.py:14-17), `f"✗"` (__main__.py:174), tabs in `__init__.py` | Latent errors | ruff and mypy (dev only), plus a CI step | S | low | n |
| F27 | B | .github/workflows/ci.yml · release-please.yml | No Python matrix (3.11 untested), mutable action tags (including `softprops` with `contents: write`), no `permissions:`/concurrency in CI, no man-page check | Supply-chain and compatibility gaps | Matrix 3.11–3.13, pin SHAs, least privilege, check the wheel's man page | S | low | n |
| F28 | B | tests/ · test_cli.py:72 | Parse-level tests only. `test_parser_cli_mode_role_only` names a mode that `main()` rejects with exit 2 | No regression net | Phase 01, and rename that test | M | low | n |
| F29 | B | AGENTS.md:26-45 · man/fomo.1.include · README · PR template | Stale docs (see section 3) | Misleads users and agents | Phase 02d | S | low | n |
| F30 | B | pyproject.toml:5-12 | Minimal package metadata | Poor wheel metadata | Add readme, license, urls, classifiers | S | low | n |
| F31 | C | scope_screen.py:38,232-235,359-362 · roles_screen.py:24,281-285 | Enter is a priority binding, so the filter's "select all visible" (`Input.Submitted`) can never fire | **Verified** dead code | Remove it (02c); redefine Enter in the filter (04a) | S | low | n |
| F32 | C | entra_screen.py:43-45 vs activation_screen.py:231-237 · roles_screen.py:25 · scope_screen.py:40 | Esc means four different things | **Verified:** Entra Esc pops the screen and loses the typed justification | One rule: Esc in a non-empty input blurs, otherwise goes back | S | low | n |
| F33 | C | azure.py:189-193 · roles_screen.py:178 · assignments_screen.py:101,163 | Date-only expiry. Eligibility end shown as `[expires …]` next to "(active)". Entra scope shows `/` | Users can't see when an activation ends | Relative time, an "eligible until" label, "Directory" instead of `/` | S | low | n |
| F34 | C | widgets.py · app.tcss:73-88 | A selected row differs only by a 1-cell `◉`, faint in the light theme | Hard to see what's selected | Style selected rows | S | low | n |
| F35 | C | all screens | No help screen. `x`, `h`/`l`, `j`/`k`, `g`/`G` and `q` (Roles, Assignments) are hidden from the footer | Poor discoverability | `?` opens a keys panel, consistent footers | S | low | n |
| F36 | C | roles_screen.py:108,213-221,365 · activation_screen.py:158-159 | Per-sub failures only show in an 8-second toast. "2/3 shown" counts disabled active rows as hidden. Activation order differs from list order. Failure statuses are unstyled and cut at 30 characters | Partial state is invisible | A persistent status, fix the counts, keep display order, map common errors | S | low | n |
| F37 | C | app.py:94-176,194 | Up to 4 synchronous subprocesses (1 s timeout each) in `__init__`. No theme override. macOS always gets dark | Up to about 4 s startup delay | An env override, `ctrl+t`, async detection | S | low | n |
| F38 | C | — | No memory of the last subs, roles, justification or duration | The common case costs 11 keys plus 3 typed strings every time | Recents (state file at 0600) | M | low | n |
| F39 | C | scope_screen.py · __main__.py | The TUI has no MG picker and no custom duration (6 presets up to 8h). The TUI activates MG-inherited roles that CLI subscription mode filters out | Inconsistent mental model | An MG tab and custom duration; document the difference | M | low | n |
| F40 | C | demo.py:175-186,250-294 | The demo never returns its MG role. Demo "active" expiries are in the past | Gaps in screenshots and tests | Return the global role, use relative dates | S | low | n |
| F41 | A | __main__.py:367-407,416 | `--demo` is ignored when `-r` is given | **Verified:** a real activation path runs | Honour it or reject the combination | S | low | 6b |
| F42 | A | __main__.py:226-235 | `--mg` doesn't drop roles inherited from parent MGs | **Verified:** `--mg Corp Owner` activates Owner at **Tenant Root** | Apply the subscription-mode scope filter | S | med | 6b |
| F43 | A | __main__.py:205-223 | An exact MG ID doesn't take precedence | **Verified:** `--mg platform` is reported as ambiguous | Check exact ID or name first | S | low | 6a |
| F44 | A | azure.py:166-186 | `0m`/`PT0M` and `P1Y` are accepted. Lowercase `pt1h` is rejected | Bad durations reach Azure | Reject zero, accept lowercase ISO | S | low | 6a |
| F45 | A | __main__.py:367 | `-r ""` is accepted, while the TUI requires a justification | Inconsistent | Reject a blank reason with exit 2 | S | low | 6b |
| F46 | D | __main__.py:172-176,264-268,335-339 | The failure detail on stderr doesn't name the role or scope | Hard to correlate when the streams are split | Add a prefix, or offer `--json` | S | low | 6b |
| F47 | D | __main__.py:345 | Ctrl+C prints a traceback | Noisy in scripts | Catch it, print a message, exit 130 | S | low | 6a |

**Checked and not a problem:**
- Leaving Roles or Assignments while their workers are still loading doesn't crash.
- Every subprocess call passes an argument list (no shell). The justification only travels inside the JSON `--body`.
- A corrupt token cache falls back to the device-code flow.

---

## 3. Docs vs behaviour mismatches

| # | Docs say | Code does | Which side should change |
|---|---|---|---|
| 1 | README:113 "first exact match wins, otherwise the first substring match" | Activates **every** exact match (across all matching subs), otherwise **every** substring match | Docs (02d) |
| 2 | README:10 and man DESCRIPTION: "parallel / concurrently" | Sequential in the TUI and the CLI | Docs (02d). Parallel TUI activation is optional in 04g |
| 3 | man and `--help` epilog: "fully delegated to az… never handles credentials or tokens" | Graph device-code flow, refresh token on disk, bearer tokens handled in-process | Docs (02d). The epilog is help text (05) |
| 4 | AGENTS.md: "az rest only, no HTTP libraries" | `urllib` for Graph and token endpoints (azure.py:16-18) and for tiering (tiering.py:13-14) | Docs (02d): record Graph as a deliberate exception |
| 5 | man: "Up to 3 roles may be selected" | Only a warning toast above 3 | Docs |
| 6 | man: `Ctrl-a` selects all visible; `/, Tab` focus the filter | `a` selects all, `Ctrl-a` isn't bound, Tab means next focus | Docs |
| 7 | man EXAMPLES | They render as just `fomo my-sub`, `fomo --mg my-mg`, `fomo --entra` because of escaped quotes inside `.B "…"` (include:119-131) | Docs |
| 8 | man: ENVIRONMENT `AZURE_CLI` | No such variable is read | Docs |
| 9 | man is missing the Entra tab, Assignments (`i`, `1`–`4`), `x`, `h`/`l`, `n`, Esc toggling on Scope, `q` meaning back on Roles | Those keys exist | Docs |
| 10 | `--mg` help: "name (substring match) or full ID" | Display-name substring, or exact **short** ID; an exact ID doesn't win | Help text (05, D9) plus F43 (6a) |
| 11 | `--demo` help: "no Azure auth required" | Ignored in CLI mode | Document it (02d); F41 (6b) |
| 12 | README:92: "switch to Entra with `l`" | Works only while the tab bar has focus | Code (04a) |
| 13 | README: device code "only required once" | Required again when the refresh token expires, and the token is reused across tenants | Docs (02d) plus F05 |
| 14 | AGENTS.md layout | Missing tiering.py, widgets.py, demo.py, entra_screen.py, assignments_screen.py, hatch_build.py, scripts/, man/ | Docs (02d) |
| 15 | `list_eligible_roles` docstring (azure.py:305): active roles "excluded" | Included, with `is_active=True` | Docstring (02d) |
| 16 | assignments_screen.py:178: "Re-run fomo --entra to re-authorise" | The cached refresh token is reused, so nothing re-authorises | Text (03e), plus `--logout` (05) |
| 17 | README: "Management group scope" as a feature | CLI only; the TUI has no MG picker | Docs (02d) or 04g |

---

## 4. UX proposals

**Common case: activate my usual role on my usual subscription** (measured headless at 80x24)

| | Current | After 04a–04b | With recents (04f) |
|---|---|---|---|
| Scope | ↓, type `prod`, ⏎, *(Space does nothing)*, ↓, Space, ⏎ | ↓, `prod`, ⏎ (highlights first row), Space, ⏎ | `1` (recent preset) |
| Roles | type `key vault`, ⏎, *(Space does nothing)*, ↓, Space, ⏎ | `key vault`, ⏎, Space, ⏎ | skipped |
| Activation | type reason, ⏎ (moves to duration), Tab, ⏎ | reason, ⏎ (activates) | reason prefilled, ⏎ |
| **Total** | **11 keys + 3 typed strings** (+2 dead Spaces) | **8 keys + 3 strings** | **2 keys** |

**Activation screen.**
```
 Current (80x24, 5 roles)                Proposed
 ┌ Activating 5 role(s) ───────────┐      ┌ Activate 3 roles ────── duration [1 hour ▾] ┐
 │ Role   Scope   Expires  Status▸ │      │ Reason ▏INC-4711 prod hotfix_______________ │
 │ …5 rows, horizontal scroll…     │      ├─────────────────────────────────────────────┤
 └─────────────────────────────────┘      │ Key Vault Admin  🟠T1  Contoso Prod  ✓ until 14:32│
  Justification [_____________]            │ Storage Blob…    🟢T3  rg-prod-stor  ⏳ needs approval│
  (Duration: not rendered)                 │ Owner            🔴T0  Contoso Dev   ✗ max is 4h [d]│
  [Activate] [Back]                        ├─────────────────────────────────────────────┤
  ╭ error log, cut off ╮                   │ ⏎ Activate  r Retry failed  i Assignments  q Quit│
                                           └─────────────────────────────────────────────┘
```

**Scope screen with recents.**
```
 Azure │ Entra │ Recent
 ── Recent ──────────────────────────────────────────────────────────
  1  Key Vault Administrator · Contoso Production   1h · "INC-…"
  2  Reader · mg-contoso                            30m
```

**Roles row.**
```
 ◉ Key Vault Administrator  Contoso Production  🟠T1  eligible → 2026-12-31
 ○ Contributor              Contoso Production  🟠T1  ● active · 47m left
```

**States to add.**
- Persistent partial-failure line: "2 of 3 subscriptions failed · e details".
- Retry on auth errors, and on "az not found".
- A loading message that names the slowest subscription.
