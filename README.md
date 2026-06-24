# fzf-pim

A terminal UI for activating Azure PIM eligible roles with multiselect.

Authentication is fully delegated to the active `az` CLI session — no credentials are stored or managed by the app.

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

## Usage

```sh
fzf-pim
```

1. Select a subscription scope
2. Multiselect the eligible roles to activate
3. Enter a justification and confirm — activation runs in parallel

**Dry-run mode** (no real API calls):

```sh
fzf-pim --dry-run
```
