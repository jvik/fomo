# Phase 03d: fix(tui), blank duration, Entra error wrapping, dbus parsing

**Group:** 3
**Findings:** F06, F20, F21
**Contract:** none

## Steps

1. **F06:** both activation screens build `Select(..., allow_blank=False)`. If the shared base from 02c exists, change it once. Keep `value="PT1H"`. The `or "PT1H"` fallback can stay; it's harmless.
2. **F20:** in `scope_screen.py`, `_on_entra_error` wraps with `msg[i:i+80]` instead of `line[i:i+80]`. Replace it with the shared `wrap_error_lines` helper from 02c, or fix the slice in place if the helper doesn't exist.
3. **F21:** in `app.py`, `_dbus_color_scheme_watcher` reads `parts[1]` without a length check. Extract the line state machine into a pure function, `_parse_color_scheme_line(state, line) -> tuple[state, theme | None]`, use it in the watcher, and guard `len(parts) > 1`.

## Tests

- **Pilot:** open the Azure activation screen. `#duration` has no blank option (`Select._allow_blank` is false, or the options list lacks the blank row), and choosing via keyboard never yields `Select.NULL`/`Select.BLANK`. With the fake `activate_role` recording its args, the duration is always a `PT…` string.
- **F20:** call `ScopeScreen._on_entra_error` (on a Pilot-mounted screen) with `"Graph request failed:\n" + "x"*120 + "\nTrace ID: 1"`. The label text contains the first line once, all 120 `x`, and "Trace ID: 1".
- **F21:** parser unit tests, including the lines `uint32`, `uint32 1`, `uint32 2` and garbage.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- Lint and the type checker are clean.

## Commits

- `fix(tui): duration can no longer be blank`
- `fix(tui): wrap long Entra error lines correctly`
- `fix(app): tolerate malformed dbus colour-scheme lines`

Tick `03d`.
