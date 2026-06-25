# fzf-pim

A terminal UI for activating Azure PIM eligible roles with multiselect.

Authentication is fully delegated to the active `az` CLI session — no credentials are stored or managed by the app.

## Platform support

Works on Linux, macOS, and WSL (Windows Subsystem for Linux).

## Prerequisites

- [Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) (`az`) — logged in with `az login`
- Python ≥ 3.11
- [`uv`](https://docs.astral.sh/uv/) or [`pipx`](https://pipx.pypa.io/)

## Install

**Using uv (recommended):**

```sh
uv tool install git+https://github.com/jvik/fzf-pim
```

**Using pipx:**

```sh
pipx install git+https://github.com/jvik/fzf-pim
```

**From a specific release wheel** (find the versioned `.whl` on the [releases page](https://github.com/jvik/fzf-pim/releases/latest)):

```sh
uv tool install https://github.com/jvik/fzf-pim/releases/latest/download/fzf_pim-VERSION-py3-none-any.whl
```

## Update

**Using uv:**

```sh
uv tool upgrade fzf-pim
```

**Using pipx:**

```sh
pipx upgrade fzf-pim
```

## Usage

```sh
fzf-pim
```

The app opens a role-type selector. Choose between:

- **Azure roles** — subscription/resource-scoped PIM roles via Azure ARM
- **Entra roles** — Microsoft Entra directory roles (Global Administrator, etc.) via Microsoft Graph

### Azure roles

1. Select a subscription scope
2. Multiselect the eligible roles to activate
3. Enter a justification and confirm — activation runs in parallel

### Entra roles

1. Select *Entra roles* from the main menu
2. The app fetches your eligible directory roles via Microsoft Graph
   - If your `az` session lacks Graph access, a **device code** sign-in prompt is shown
3. Multiselect the roles to activate (already-active roles are marked)
4. Choose a duration, enter a justification, and confirm

**Dry-run mode** (no real API calls):

```sh
fzf-pim --dry-run
```

**Verbose logging** (write debug logs to a file):

```sh
fzf-pim --log /tmp/fzf-pim.log
```

Logs include all `az rest` and Graph API calls and responses. Useful for troubleshooting.
