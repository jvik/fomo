# Phase 04e: feat(tui), help panel, consistent footers, theme override

**Group:** 4
**Findings:** F35, F37
**Contract:** none

## Steps

### 1. Help (F35)

- `?` on every screen opens a modal "Keys" screen generated from the active screen's `BINDINGS`, including hidden ones, with readable labels. Escape or `?` closes it.
- Footers: every screen shows Quit (`q`, or `ctrl+c` while typing) and Back where it applies.
- Hidden-but-useful bindings get `show=False` labels so the help screen lists them: `x` Toggle, `j`/`k` Move, `g`/`G` Top/Bottom, `h`/`l` Tabs.

### 2. Theme (F37)

- `FOMO_THEME=dark|light` skips detection entirely.
- `ctrl+t` toggles dark and light at runtime (`priority=True`, so it works while typing).
- Detection must not block startup for seconds:
  1. Run `_system_is_dark` in a thread worker after mount, starting with `fomo-dark`.
  2. Cut each subprocess timeout to 0.3 s.
  3. Stop at the first decisive answer.
  4. On macOS (`sys.platform == "darwin"`), use `defaults read -g AppleInterfaceStyle`.
  5. Respect `NO_COLOR` by doing nothing special; Textual handles it.

## Tests

- Pilot: `?` on Scope, Roles, Activation and Assignments opens the Keys screen, and it lists `x` and `h`/`l` where relevant.
- `FOMO_THEME=light`: `app.theme == "fomo-light"` and `_system_is_dark` isn't called. Monkeypatch it to raise.
- `ctrl+t` toggles the theme, also with an Input focused.
- Startup doesn't call the detection subprocesses synchronously in `__init__`. Monkeypatch `subprocess.run` to sleep 2 s, and assert the app mounts in under 1 s.

## Docs

Update the man include ENVIRONMENT section with `FOMO_THEME`, and add `?` and `ctrl+t` to the keys. Mention them in the README.

## Verify

- `.venv/bin/python -m pytest -q` passes.
- Lint and the type checker are clean.

## Commits

- `feat(tui): keyboard help panel on every screen`
- `feat(tui): FOMO_THEME override, ctrl+t toggle, non-blocking theme detection`

Tick `04e`.
