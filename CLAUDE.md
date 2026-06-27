# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repository.

## What this library is

`bleak-smlight` is the **host-side** Bleak backend that lets a Python app
receive Bluetooth advertisements via a SMLIGHT SLZB-U BLE proxy (an ESP32-S3
running SLZB-OS). It is _not_ the firmware — the SLZB firmware exposes a small
UDP BLE-proxy server, and the wire protocol/client live in
[`pysmlight`](https://github.com/smlight-tech/pysmlight)
(`pysmlight.BleProxyClient`).

The proxy is **scan-only**: it relays raw BLE advertisements but has no
GATT/active-connection support. There is therefore no Bleak _client_ here — only
a non-connectable `BaseHaRemoteScanner`. This package wires a
`pysmlight.BleProxyClient` to a `SMLIGHTScanner` and registers it with
`habluetooth`, with no Home Assistant dependency. See `docs/architecture.md`
for the full picture.

## Layout

- `src/bleak_smlight/` — package source (importable as `bleak_smlight`).
- `src/bleak_smlight/backend/scanner.py` — `SMLIGHTScanner`, a
  Cython-compiled `BaseHaRemoteScanner` subclass whose
  `_handle_raw_advertisement` is the callback handed to
  `pysmlight.BleProxyClient`.
- `src/bleak_smlight/connect.py` — public `connect_scanner()` entry point; it
  builds the scanner + `BleProxyClient` pair and returns a `SMLIGHTClientData`.
  Also defines `SLZB_BLE_SERVER_PORT` (default UDP port `5050`).
- `src/bleak_smlight/connection_manager.py` — `SMLIGHTConnectionManager` +
  `SMLIGHTDeviceConfig`, the standalone (HA-free) entry point that registers
  the scanner with `habluetooth.get_manager()` and drives the proxy client.
- `tests/` — pytest suite (mirrors `src/` layout under `tests/backend/`).
- `docs/` — Sphinx documentation (`make -C docs html` to build locally).
- `examples/` — minimal runnable usage examples.

## Toolchain

- **Python**: `>=3.12, <4`. Do not use syntax or stdlib added after 3.12.
- **Package manager**: [Poetry](https://python-poetry.org). Install with
  `poetry install`. Dev dependencies include `pytest`, `pytest-asyncio`,
  `pytest-cov`, `pytest-codspeed`.
- **Build**: Poetry + a Cython build step (`build_ext.py`). Generated `*.c`
  files are excluded from the sdist.

## Style and formatting — non-negotiable

The pre-commit suite runs in CI and **will fail the build** if any hook fails.
Match these rules locally before pushing or your PR will be red.

- **Line length: 88 characters.** Ruff (via `tool.ruff.line-length` in
  `pyproject.toml`) enforces this for both linting and formatting. It applies
  to **docstrings and comments too** — ruff's `E501` does not exempt them.
  Wrap long docstring summaries onto multiple lines rather than letting them
  spill past column 88.
- **Formatter**: `ruff format` (the `ruff-format` pre-commit hook). Run
  `poetry run ruff format .` to fix formatting in bulk.
- **Linter**: `ruff` with `select = [B, D, C4, S, F, E, W, UP, I, RUF, ...]`.
  Tests are exempt from most `D` (docstring) rules and from `S101` (assert).
  See `[tool.ruff.lint.per-file-ignores]` in `pyproject.toml` for the full set.
- **Type checking**: `mypy` in strict-ish mode (`disallow_untyped_defs`,
  `disallow_any_generics`, `warn_unreachable`, `warn_unused_ignores`). Tests
  are allowed untyped defs. The pre-commit mypy hook lists the typed runtime
  deps (`pysmlight`, `habluetooth`, `bluetooth-data-tools`) in
  `additional_dependencies`; add to that list if you import a new typed
  package.
- **Modern syntax**: `pyupgrade --py312-plus` runs in pre-commit. Use 3.12+
  syntax (`X | None` over `Optional[X]`, PEP 604 unions, etc.).
- **Imports**: `ruff` handles `isort`. First-party packages are
  `bleak_smlight` and `tests`.
- **YAML / Markdown / JSON**: formatted by `prettier` with `--tab-width 2`.
- **Commits / PR titles**: [Conventional Commits](https://www.conventionalcommits.org).
  PRs are squash-merged, so the **PR title** becomes the commit on `main` and
  drives python-semantic-release's version bump. The `pr-title` CI job
  (`amannn/action-semantic-pull-request`) is the sole enforcement point — there
  is no commit-msg hook. Use `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`,
  `test:`, `ci:`, etc., with a lowercase subject.
- **Misc hygiene hooks** (from `pre-commit/pre-commit-hooks`):
  `debug-statements`, `check-builtin-literals`, `check-case-conflict`,
  `check-docstring-first`, `check-json`, `check-toml`, `check-xml`,
  `check-yaml`, `detect-private-key`, `end-of-file-fixer`,
  `trailing-whitespace`.

The canonical command to validate everything locally is:

```shell
poetry run pre-commit run --all-files
```

Run it before pushing — CI runs the same set.

## Tests

- Run the full suite: `poetry run pytest`.
- A single file: `poetry run pytest tests/backend/test_scanner.py -v`.
- Coverage is collected automatically (`--cov=bleak_smlight`); the report is
  printed to the terminal. Note `scanner.py` reports 0% when it has been
  Cython-compiled to a `.so` (coverage cannot trace compiled modules); run with
  `SKIP_CYTHON=1` if you need line coverage on it.
- Tests are `pytest-asyncio` based — mark coroutine tests with
  `@pytest.mark.asyncio`.
- Mirror new source modules with a matching `tests/backend/test_<name>.py`.
- Cython is built in-place by Poetry; if imports fail with "module not
  compiled", re-run `poetry install`.

## Common pitfalls

- **Docstring overruns are the #1 CI failure.** Test functions with long
  descriptive docstrings often cross column 88. Either wrap the summary onto
  multiple lines or shorten it.
- **Know what `pysmlight` decodes vs. what the scanner must convert.** The
  proxy callback signature is `(mac_bytes, rssi, address_type, raw_data)` —
  `Callable[[bytes, int, int, bytes], None]`. `pysmlight` already decodes the
  signed RSSI `int` (pass it through), but the MAC arrives as raw little-endian
  `bytes`, **not** a colon-formatted string: `_handle_raw_advertisement` must
  convert it with `int_to_bluetooth_address(int.from_bytes(mac_bytes, "little"))`.
  Don't remove that conversion.
- **Don't add Home Assistant imports.** This library is intentionally HA-free;
  `SMLIGHTConnectionManager` + `SMLIGHTDeviceConfig` is the standalone entry
  point.
- **Don't add GATT/active-connection code.** The SLZB proxy is scan-only; the
  scanner is always registered non-connectable.

## When in doubt

- Read `docs/architecture.md` for how the pieces connect.
- Read `CONTRIBUTING.md` for the human-oriented contribution flow.
- Read `pyproject.toml` — it is the source of truth for tool config.
