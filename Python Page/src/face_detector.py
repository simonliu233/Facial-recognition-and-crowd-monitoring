"""HOG detector without MediaPipe/TensorFlow runtime dependencies."""
class FaceDetector:
    def __init__(self):
        import face_recognition
        self.backend = face_recognition

    def detect(self, frame):
        import numpy as np
        locations = self.backend.face_locations(np.ascontiguousarray(frame[:, :, ::-1]), model="hog")
        return [(left, top, right-left, bottom-top) for top, right, bottom, left in locations]
