"""Offline OpenCV age/gender models; optional local emotion model."""
import logging
from .config import MODEL_DIR

logger = logging.getLogger(__name__)

class AgeGenderEmotionPredictor:
    def __init__(self):
        import cv2
        self.cv2 = cv2
        self.age_net = cv2.dnn.readNetFromCaffe(str(MODEL_DIR / "age_deploy.prototxt"), str(MODEL_DIR / "age_net.caffemodel"))
        self.gender_net = cv2.dnn.readNetFromCaffe(str(MODEL_DIR / "gender_deploy.prototxt"), str(MODEL_DIR / "gender_net.caffemodel"))
        self.emotion_model = None
        self.emotion_error = None
        self._emotion_attempted = False

    def _load_emotion(self):
        if self._emotion_attempted:
            return
        self._emotion_attempted = True
        try:
            import os
            import json
            import h5py
            os.environ.setdefault("KERAS_BACKEND", "torch")
            import keras
            # FER's legacy HDF5 JSON contains no serialized TensorFlow objects.
            # Decode standard JSON directly so Keras does not import TensorFlow.
            from keras.src.legacy.saving import saving_utils, legacy_h5_format
            with h5py.File(MODEL_DIR / "emotion_model.hdf5", "r") as handle:
                config = handle.attrs["model_config"]
                if isinstance(config, bytes):
                    config = config.decode("utf-8")
                self.emotion_model = saving_utils.model_from_config(json.loads(config))
                legacy_h5_format.load_weights_from_hdf5_group(handle["model_weights"], self.emotion_model)
        except Exception as exc:
            self.emotion_error = type(exc).__name__
            logger.warning("Optional emotion model unavailable: %s", exc)

    def predict(self, face_image):
        import numpy as np
        cv2 = self.cv2
        if face_image.size == 0:
            return "Unknown", "Unknown", "Unavailable"
        blob = cv2.dnn.blobFromImage(face_image, 1.0, (227, 227),
                                     (78.4263377603, 87.7689143744, 114.895847746), swapRB=False)
        self.age_net.setInput(blob)
        self.gender_net.setInput(blob)
        ages = ["0–2", "4–6", "8–12", "15–20", "25–32", "38–43", "48–53", "60+"]
        age = ages[int(self.age_net.forward()[0].argmax())]
        gender = ["Male", "Female"][int(self.gender_net.forward()[0].argmax())]
        self._load_emotion()
        emotion = "Unavailable"
        if self.emotion_model is not None:
            gray = cv2.cvtColor(face_image, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (64, 64)).astype(np.float32)
            gray = ((gray / 255.0) - 0.5) * 2.0
            import torch
            with torch.inference_mode():
                probabilities = self.emotion_model(torch.from_numpy(gray[None, :, :, None]), training=False).detach().cpu().numpy()[0]
            emotion = ["Angry", "Disgust", "Fear", "Happy", "Sad", "Surprise", "Neutral"][int(np.argmax(probabilities))]
        return age, gender, emotion
