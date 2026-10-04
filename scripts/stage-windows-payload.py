"""Stage only application code; exclude tests and machine-specific bytecode."""
from pathlib import Path
import shutil
root = Path(__file__).resolve().parents[1]
target = root / 'dist/windows-payload'
if target.exists():
    shutil.rmtree(target)
target.mkdir(parents=True)
for name in ['ffbridge', 'lua', 'scripts']:
    shutil.copytree(root / 'resolve' / name, target / name,
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
shutil.copy2(root / 'resolve/ffbridge_launcher.py', target / 'ffbridge_launcher.py')
