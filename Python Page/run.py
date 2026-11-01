"""Start one local server. No domain, cloud database, TLS or admin rights needed."""
import argparse
import importlib
import logging
import os
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent
os.environ.setdefault("KERAS_BACKEND", "torch")
os.environ.setdefault("YOLO_AUTOINSTALL", "false")
os.environ.setdefault("YOLO_CONFIG_DIR", str(BASE / "data" / "local" / "ultralytics"))
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
sys.path.insert(0, str(BASE))

def main():
    parser = argparse.ArgumentParser(description="Local FaceTech")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--check", action="store_true", help="Check actual core imports and model files")
    args = parser.parse_args()
    if sys.version_info < (3,10) or sys.version_info >= (3,12):
        print("Use the project launcher with Python 3.10 or 3.11. The tested environment is Python 3.10.")
        return 1
    if args.check:
        failed = False
        for name in ["flask", "flask_sqlalchemy", "flask_login", "flask_wtf", "flask_bcrypt",
                     "cv2", "numpy", "face_recognition", "torch", "torchvision", "ultralytics", "waitress", "keras", "h5py"]:
            try:
                importlib.import_module(name)
                print("OK", name, flush=True)
            except Exception as exc:
                failed = True
                print("FAIL", name, type(exc).__name__, str(exc), flush=True)
        for name in ["yolov8n.pt", "models/age_net.caffemodel", "models/gender_net.caffemodel",
                     "models/age_deploy.prototxt", "models/gender_deploy.prototxt", "models/emotion_model.hdf5"]:
            exists = (BASE / name).is_file()
            print("OK" if exists else "MISSING", name)
            failed = failed or not exists
        return int(failed)
    import torch
    torch.set_num_threads(min(4, os.cpu_count() or 1))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    from app import create_app
    from waitress import serve
    app = create_app()
    url = f"http://127.0.0.1:{args.port}/"
    print(f"FaceTech local: {url}", flush=True)
    print("Press Ctrl+C to stop. Register a local account on first use.", flush=True)
    if not args.no_browser:
        import threading
        import webbrowser
        timer = threading.Timer(1.5, lambda: webbrowser.open(url))
        timer.daemon = True
        timer.start()
    try:
        serve(app, host="127.0.0.1", port=args.port, threads=6)
    except OSError as exc:
        print(f"Cannot start on port {args.port}: {exc}. Try --port 5050.", file=sys.stderr)
        return 1
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
