# Phase 02c: refactor(tui), de-duplicate screens and introduce a Backend

**Group:** 2
**Findings:** F23, F31 (removal only)
**Contract:** none. No visible behaviour change; the smoke tests must pass unchanged.

## Steps

### 1. Backend

Add a `Backend` (in `fomo/backend.py`) chosen once in `PimApp.__init__`:
- `AzureBackend` delegates to `fomo.azure`, looking up `azure.<fn>` **at call time** so the tests' monkeypatching keeps working.
- `DemoBackend` delegates to `fomo.demo`.

Methods: `list_subscriptions`, `list_eligible_roles(sub_id)`, `list_entra_eligible_roles(on_device_code, stop_event)`, `list_active_arm_assignments()`, `list_active_entra_assignments(on_device_code, stop_event)`, `activate_role(role, justification, duration)`, `activate_entra_role(...)`, and the property `dry_run` (`app.dry_run or demo_mode`).

- Screens use `self.app.backend` instead of `getattr(self.app, "demo_mode", False)` and `self.app.dry_run or …`.
- `Backend` performs no I/O itself, so azure.py remains the only Azure I/O module. Mention that in its docstring.

### 2. Tiering API

- Add `tiering.ensure_azure_loaded()` and `tiering.ensure_entra_loaded()`, which load once and are thread-safe (a `threading.Lock`).
- Screens stop reading `tiering._azure_index` and `tiering._entra_index`.
- Keep the call sites **inside** the same `try` blocks as today. Moving them is 03b's job, with tests.

### 3. Shared activation base

Create `fomo/screens/_activation_base.py`:
- shared `_DURATION_OPTIONS`, `_format_status`, `_append_error`, `_on_activation_done`
- the justification and duration form compose helper
- the per-row status update

`ActivationScreen` and `EntraActivationScreen` subclass it.
- **Preserve the current differences exactly.** For now the Entra screen keeps its priority Escape and `q` binding, and the Azure screen keeps its blur-first Escape; 04b unifies them.
- Keep the widget IDs, texts and table columns.

### 4. Shared helpers

Create `fomo/screens/_common.py`:
- `VimNavMixin` for the `vim_down`/`up`/`top`/`bottom` actions, used by the three screens that copy them
- `device_code_markup(url, code)`
- `wrap_error_lines(msg, width=80)`, the **correct** line-based version from `assignments_screen.py`

Use `wrap_error_lines` only in `assignments_screen.py` for now. **Leave `scope_screen.py`'s buggy wrap (F20) as it is**; 03d fixes it with a test.

### 5. Remove dead code (F31)

Remove the `Input.Submitted` handlers on `#filter` and `#entra-filter` in ScopeScreen and RolesScreen. They're unreachable because Enter is a priority binding. Add a short comment at the Enter binding saying Enter in a filter moves focus to the list. 04a builds on this.

## Verify

- `.venv/bin/python -m pytest -q` passes, with the smoke tests unchanged.
- A throwaway Pilot script in `plan/logs/scratch/` walks Scope → Roles → Activation → Done and the Entra tab in demo mode at 80x24 and 120x36, and the text dumps look the same as before. Use `app.screen._compositor.render_strips()` to dump each screen as text.
- Ruff and the type checker are clean.

## Commits

- `refactor(tui): add Backend to separate demo and Azure data sources`
- `refactor(tiering): public ensure_*_loaded API`
- `refactor(tui): share activation screen logic between Azure and Entra`
- `refactor(tui): share vim navigation and device-code helpers`
- `refactor(tui): remove unreachable filter submit handlers`

Tick `02c`.
