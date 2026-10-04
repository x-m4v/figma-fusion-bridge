"""Run the Windows GUI, install scripts, or act as Resolve's bundled CLI."""
import os
import sys
from pathlib import Path

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'resolve'))
os.environ['PYTHONUTF8'] = '1'
for stream in (sys.stdout, sys.stderr):
    if stream and hasattr(stream, 'reconfigure'):
        stream.reconfigure(encoding='utf-8')


def main():
    if sys.argv[1:2] == ['--cli']:
        from ffbridge.cli import main as cli
        return cli(sys.argv[2:])
    if sys.argv[1:2] == ['--install']:
        from ffbridge_app.installer import install
        print('Installed Resolve scripts at', install())
        print('Restart Resolve, then import figma-plugin/manifest.json in Figma desktop.')
        return 0
    if sys.argv[1:2] == ['--self-test']:
        import tempfile
        from ffbridge_app.server import Bridge
        from ffbridge.client import BridgeClient, Session
        with tempfile.TemporaryDirectory() as root:
            bridge = Bridge(root)
            try:
                bridge.start([0])
                assert BridgeClient(Session(bridge.state.port, bridge.state.token)).status()['version'] == '0.1.0'
            finally:
                bridge.stop()
        print('Packaged bridge HTTP self-test passed.')
        return 0

    import tkinter as tk
    from tkinter import messagebox
    from ffbridge_app.server import Bridge
    from ffbridge_app.installer import install
    window = tk.Tk()
    window.title('Figma Fusion Bridge')
    window.geometry('440x290')
    bridge = Bridge()
    try:
        bridge.start()
    except OSError as error:
        messagebox.showerror('Figma Fusion Bridge', str(error))
        window.destroy()
        return 1
    tk.Label(window, text='Figma Fusion Bridge', font=('Segoe UI', 18)).pack(pady=12)
    tk.Label(window, text=f'Local bridge listening on port {bridge.state.port}').pack()
    code = tk.StringVar(value=bridge.state.code)
    tk.Label(window, text='Enter this pairing code in the Figma plugin:').pack(pady=6)
    tk.Label(window, textvariable=code, font=('Consolas', 24)).pack()
    tk.Button(window, text='New pairing code', command=lambda: code.set(bridge.state.new_code())).pack()

    def setup():
        try:
            install()
            messagebox.showinfo('Installed', 'Restart Resolve. On the Fusion page, use Workspace > Scripts > Figma Fusion Bridge - Receive.')
        except OSError as error:
            messagebox.showerror('Installation failed', str(error))

    tk.Button(window, text='Install / repair Resolve scripts', command=setup).pack(pady=8)
    tk.Label(window, text='Keep this window open while sending designs.').pack()

    def refresh():
        import time
        if time.monotonic() > bridge.state.expires:
            code.set(bridge.state.new_code())
        window.after(1000, refresh)

    def close():
        bridge.stop()
        window.destroy()

    window.protocol('WM_DELETE_WINDOW', close)
    window.after(1000, refresh)
    window.mainloop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
