# Validation — 2026-10-04

## Local results

Host: Apple Silicon macOS. Node 24.13.0, Python 3.9.6, Swift 6.4.

- Figma plugin bundle and schema build: passed.
- TypeScript checks for both packages: passed.
- npm audit after updating the plugin workspace esbuild to 0.28.2: zero known vulnerabilities.
- Python/Lua suite: **279 passed, 1 skipped**. The skipped check enumerates actual Windows GDI fonts.
- Swift checks: **49 passed**, including installation, repair and uninstall in isolated directories.
- macOS release .app build: passed; arm64 architecture and ad-hoc signature verified.
- Actual native .app startup and HTTP-to-CLI smoke test: passed with isolated data, including image roundtrip and generated graph.
- Real loopback HTTP: discovery, pairing, authorization, CORS, rejected invalid host,
  checksum verification, upload/download, transfer, report and long poll passed.
- Actual CLI retrieved the starter document through HTTP and produced a Fusion `.setting` file.
- Lua 5.1 executed real helper code; Windows JSON path decoding, command construction,
  script syntax and quoted paths passed. Local tests simulated the Windows shell;
  the GitHub Windows job also exercises actual Windows process launch and packaged CLI.

The original macOS installer omitted its Lua helper from the app bundle and looked
for an obsolete Python menu script. Both issues are fixed. Native installer tests
now verify that three Lua commands and the supporting library are installed.

## Native Windows and hosted CI

Both native jobs passed in [GitHub Actions run 37199978426](https://github.com/x-m4v/figma-fusion-bridge/actions/runs/37199978426), for code commit `4517310`.

- Windows x64: Python/Lua checks including real GDI fonts passed; EXE packaging,
  loopback HTTP self-test and hidden GUI initialization passed.
- Windows installation and actual LuaJIT → CreateProcessW → packaged CLI passed
  with Unicode/spaces in both the data directory and executable directory.
- macOS ARM64: Python/Lua and Swift checks passed; .app build, signature
  verification and release packaging passed on the macOS 14 hosted runner.
- Both ZIP payloads and SHA-256 checksums were checked after downloading. Plugin
  bundles, platform installers and applicable license texts are present; tests,
  bytecode caches, local credentials and user session files are excluded.

Installable packages: [v0.1.0-preview.1](https://github.com/x-m4v/figma-fusion-bridge/releases/tag/v0.1.0-preview.1).

## Checks still requiring application access

Neither offline tests nor a successful executable build prove visual fidelity or
renderer stability inside Resolve. Full Figma Desktop → bridge → Resolve acceptance,
color matching, Free/Studio behavior and each supported Resolve release remain
pending until the [manual checklist](MANUAL_ACCEPTANCE.ru.md) is completed.
No real user compositions were modified by this audit.

## Current feature boundaries

Receive adds a new graph; it does not apply existing re-sync plans or preserve old
animation automatically. Pull is a placeholder endpoint. Live Sync refreshes the
available transfer only. Some strokes/polygons are rejected by the existing safe
renderer pass. The pricing-card offline example is not a passing Receive example.
