# Third-party notices

Original project code is MIT-licensed; third-party code retains its own terms.
Exact notices for installed npm dependencies are in `licenses/`.

| Dependency | Purpose | License |
|---|---|---|
| Zod 3.25.76 | Schema validation; may be bundled into plugin code | MIT |
| Figma plugin typings 1.138.0 | Build-time API type definitions | MIT |
| TypeScript | Build-time compiler | Apache-2.0 |
| esbuild (root and plugin workspace versions) | Build-time bundler | MIT |
| @types/node, undici-types | Build-time type definitions | MIT |
| CPython (Windows release) | Bundled interpreter and standard library | PSF license stack; see Python-LICENSE.txt in release |
| Tcl/Tk (Windows release) | GUI runtime | Tcl/Tk licenses in release |
| PyInstaller bootloader | Windows executable launcher | GPL with bootloader exception; applicable runtime helpers have their own notices |

Tests additionally use pytest (MIT) and Lupa (MIT; includes Lua under its own MIT notice). They are not shipped to users.

The Windows build must collect the actual runtime license files, including
Python's bundled third-party notices, Tcl/Tk, PyInstaller and runtime dependencies.
The release assembler copies the resulting `licenses/` directory. See
`scripts/collect-windows-licenses.py`. Dependencies cannot be relicensed as MIT.

Figma, DaVinci Resolve and Fusion are names of their respective owners. This
project is an independent integration and is not endorsed by Figma or Blackmagic
Design. The applications, vendor SDK binaries, fonts, templates, and user design
assets are not included in source or release packages.
