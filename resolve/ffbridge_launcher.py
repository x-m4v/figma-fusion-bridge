"""Stable entry point for Resolve's external Python process."""
import sys
from ffbridge.cli import main
if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
