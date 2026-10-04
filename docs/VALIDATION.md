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
  the GitHub Windows job also exercises actual cmd.exe and packaged CLI.

The original macOS installer omitted its Lua helper from the app bundle and looked
for an obsolete Python menu script. Both issues are fixed. Native installer tests
now verify that three Lua commands and the supporting library are installed.

## Native Windows and hosted CI

The workflow `.github/workflows/ci.yml` performs native Windows x64 and macOS ARM64
builds and uploads installation ZIPs. Actual CI run links/results are recorded here
after publication. Windows checks cover real GDI enumeration, packaged HTTP
self-test, isolated installation, and Lua → cmd.exe → packaged CLI.

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
