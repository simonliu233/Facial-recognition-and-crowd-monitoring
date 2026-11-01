"""Face recognition blueprint for the local application."""
import threading
from flask import Blueprint, current_app, jsonify, render_template
from flow_counter import decode_image
from src.config import PHOTO_DIR
from src.face_recognizer import FaceRecognizer
from src.age_gender_emotion_predictor import AgeGenderEmotionPredictor

face_bp = Blueprint("face", __name__)

class FaceService:
    def __init__(self, database, photo_dir=PHOTO_DIR, cache_file=None):
        self.database = database
        self.photo_dir = photo_dir
        self.cache_file = cache_file
        self.recognizer = None
        self.predictor = None
        self.lock = threading.RLock()

    def process(self, frame, labels):
        import cv2
        import numpy as np
        import face_recognition
        with self.lock:
            if self.recognizer is None:
                self.recognizer = FaceRecognizer(cache_file=self.cache_file)
                self.predictor = AgeGenderEmotionPredictor()
            self.recognizer.load_known_faces(self.photo_dir, labels)
            height, width = frame.shape[:2]
            scale = min(1.0, 800 / width)
            small = cv2.resize(frame, (int(width*scale), int(height*scale))) if scale < 1 else frame
            rgb = np.ascontiguousarray(small[:, :, ::-1])
            locations = face_recognition.face_locations(rgb, number_of_times_to_upsample=1, model="hog")
            features = face_recognition.face_encodings(rgb, known_face_locations=locations)
            faces = []
            for location, encoding in zip(locations, features):
                top, right, bottom, left = [round(v / scale) for v in location]
                top, left, bottom, right = max(top, 0), max(left, 0), min(bottom, height), min(right, width)
                name, confidence = self.recognizer.identify(encoding)
                age, gender, emotion = self.predictor.predict(frame[top:bottom, left:right])
                self.database.add_record(name, emotion, confidence)
                faces.append({"name": name, "confidence": confidence, "age": age, "gender": gender,
                              "emotion": emotion, "x": left, "y": top, "w": right-left, "h": bottom-top})
            return {"faces": faces, "count": len(faces),
                    "gallery_size": len(self.recognizer.known_face_names),
                    "gallery_warnings": self.recognizer.warnings,
                    "emotion_available": bool(self.predictor.emotion_model)}

@face_bp.get("/")
def index():
    return render_template("detect.html")

@face_bp.post("/process_frame")
def process_frame():
    try:
        frame = decode_image()
        labels = current_app.extensions["face_labels"]()
        return jsonify(current_app.extensions["face_service"].process(frame, labels))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        current_app.logger.exception("Face recognition failed")
        return jsonify(error="人臉模型處理失敗，請查看本機終端的錯誤訊息。"), 503

@face_bp.get("/records")
def view_records():
    return render_template("records.html", records=current_app.extensions["analytics"].get_records())
