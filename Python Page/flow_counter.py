"""Local people counting blueprint: YOLOv8 + ByteTrack + observed crossings."""
import json
import os
import threading
import time
from pathlib import Path

from flask import Blueprint, current_app, jsonify, render_template, request

from src.config import BASE_DIR, DATA_DIR
from src.database_manager import DatabaseManager, get_local_datetime
from src.line_counter import LineCrossingCounter

flow_bp = Blueprint("flow", __name__)
class StreamBusy(ValueError):
    pass

class FlowCounter:
    def __init__(self, database=None, model=None, settings_path=None):
        self.db = database or DatabaseManager()
        self.model = model
        self.lock = threading.RLock()
        self.counter = LineCrossingCounter()
        self.settings_path = Path(settings_path or DATA_DIR / "flow-settings.json")
        if self.settings_path.is_file():
            cfg = json.loads(self.settings_path.read_text(encoding="utf-8"))
            self.counter.configure(cfg["axis"], cfg["line_position"], cfg["dead_band"],
                                   (cfg["roi_start"], cfg["roi_end"]))
        self.session_counts = {"left_to_right": 0, "right_to_left": 0}
        self.stream_id = None
        self.last_frame = 0.0
        self.last_frame_index = -1
        self.last_size = None

    def _load_model(self):
        if self.model is None:
            weights = Path(os.environ.get("FACE_APP_YOLO_MODEL", str(BASE_DIR / "yolov8n.pt"))).resolve()
            if not weights.is_file():
                raise RuntimeError(f"Person detection model is missing: {weights}")
            os.environ.setdefault("YOLO_CONFIG_DIR", str(DATA_DIR / "ultralytics"))
            from ultralytics import YOLO, settings
            settings.update({"sync": False, "hub": False})
            from ultralytics.hub.utils import events
            events.enabled = False
            self.model = YOLO(str(weights))

    def _reset_tracks(self):
        self.counter.clear()
        self.session_counts = {"left_to_right": 0, "right_to_left": 0}
        if self.model is not None and getattr(self.model, "predictor", None):
            for tracker in getattr(self.model.predictor, "trackers", []):
                tracker.reset()
        self.last_frame_index = -1
        self.last_size = None

    def release_stream(self, stream_id):
        with self.lock:
            if stream_id == self.stream_id:
                self.stream_id = None
                self._reset_tracks()

    def stats(self):
        return {**self.db.get_counts(), **self.counter.settings(),
                "session_left_to_right": self.session_counts["left_to_right"],
                "session_right_to_left": self.session_counts["right_to_left"],
                "forward_label": "左 → 右" if self.counter.axis == "x" else "上 → 下",
                "backward_label": "右 → 左" if self.counter.axis == "x" else "下 → 上",
                "timestamp": get_local_datetime().isoformat()}

    def configure(self, cfg):
        with self.lock:
            self.counter.configure(
                cfg.get("axis", self.counter.axis),
                cfg.get("line_position", self.counter.position),
                cfg.get("dead_band", self.counter.band),
                (cfg.get("roi_start", self.counter.roi[0]), cfg.get("roi_end", self.counter.roi[1])),
            )
            self._reset_tracks()
            self.settings_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.settings_path.with_suffix(".tmp")
            temp.write_text(json.dumps(self.counter.settings()), encoding="utf-8")
            temp.replace(self.settings_path)
            return self.stats()

    def process_frame(self, frame, stream_id="local", frame_index=None):
        with self.lock:
            now = time.monotonic()
            if self.stream_id and stream_id != self.stream_id and now - self.last_frame < 20:
                raise StreamBusy("另一個分頁正在計數，請先在該分頁按「停止」。")
            changed = stream_id != self.stream_id
            if changed or (self.last_frame and now - self.last_frame > 4.0) or frame.shape[:2] != self.last_size:
                self._reset_tracks()
                self.stream_id = stream_id
            if frame_index is not None and frame_index <= self.last_frame_index:
                raise ValueError("影格順序錯誤，請停止後重新開始。")
            self.last_frame = now
            self.last_size = frame.shape[:2]
            if frame_index is not None:
                self.last_frame_index = frame_index
            self._load_model()
            result = self.model.track(
                frame, persist=True, classes=[0], verbose=False, conf=0.1, iou=0.5,
                imgsz=640, tracker=str(BASE_DIR / "config" / "bytetrack-local.yaml"),
                device=os.environ.get("FACE_APP_DEVICE", "cpu"),
            )[0]
            height, width = frame.shape[:2]
            observations, boxes = [], []
            if result.boxes is not None and result.boxes.id is not None:
                coordinates = result.boxes.xyxy.cpu().numpy()
                identities = result.boxes.id.int().cpu().tolist()
                scores = result.boxes.conf.cpu().tolist()
                for xyxy, identity, score in zip(coordinates, identities, scores):
                    x1, y1, x2, y2 = map(float, xyxy)
                    x1, x2 = max(0.0, x1), min(float(width), x2)
                    y1, y2 = max(0.0, y1), min(float(height), y2)
                    foot_x, foot_y = (x1 + x2) / (2 * width), y2 / height
                    observations.append((identity, foot_x, foot_y))
                    boxes.append({"id": identity, "x": x1, "y": y1, "w": x2-x1, "h": y2-y1,
                                  "confidence": float(score)})
            events = self.counter.update(observations, now)
            if events:
                self.db.record_crossings(events, self.counter.axis)
                for event in events:
                    self.session_counts[event["direction"]] += 1
            self.last_frame = time.monotonic()
            return {**self.stats(), "boxes": boxes, "events": events,
                    "active_tracks": len(observations),
                    "processing_time": round(time.monotonic() - now, 3)}

def get_counter():
    return current_app.extensions["flow_counter"]

def decode_image():
    import cv2
    import numpy as np
    if "image" not in request.files:
        raise ValueError("請提供 image 圖片欄位。")
    data = request.files["image"].read()
    if not data:
        raise ValueError("圖片不能為空。")
    frame = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("無法解碼圖片。")
    if frame.shape[0] * frame.shape[1] > 4096 * 4096:
        raise ValueError("圖片過大，請使用 1920×1080 或更小的影格。")
    return frame

@flow_bp.get("/")
def index():
    return render_template("flow_counter.html")

@flow_bp.get("/get_current_stats")
def get_current_stats():
    return jsonify(get_counter().stats())

@flow_bp.post("/process_flow_frame")
def process_flow_frame():
    try:
        frame = decode_image()
        stream_id = request.form.get("stream_id", "local")[:128]
        index = request.form.get("frame_index")
        result = get_counter().process_frame(frame, stream_id, int(index) if index else None)
        return jsonify(result)
    except StreamBusy as exc:
        return jsonify(error=str(exc)), 409
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        current_app.logger.exception("Person tracking failed")
        return jsonify(error="人流模型處理失敗，請查看本機終端的錯誤訊息。"), 503

@flow_bp.post("/settings")
def settings():
    try:
        cfg = request.get_json(silent=True)
        if not isinstance(cfg, dict):
            raise ValueError("請提供設定物件。")
        return jsonify(get_counter().configure(cfg))
    except (ValueError, TypeError, KeyError) as exc:
        return jsonify(error=str(exc)), 400

@flow_bp.post("/reset_counters")
def reset_counters():
    counter = get_counter()
    with counter.lock:
        counter.db.reset_counts()
        counter._reset_tracks()
        return jsonify(counter.stats())

@flow_bp.post("/stop_camera")
def stop_camera():
    get_counter().release_stream(request.form.get("stream_id", "local"))
    return jsonify(status="stopped")

@flow_bp.get("/records")
def view_records():
    return render_template("flow_records.html", records=get_counter().db.get_flow_records())
