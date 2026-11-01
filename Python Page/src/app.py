"""Compatibility entry point. Start the unified local application."""
import runpy
from pathlib import Path
if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "run.py"), run_name="__main__")
