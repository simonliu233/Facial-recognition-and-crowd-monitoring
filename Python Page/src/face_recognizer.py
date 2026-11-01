"""Face gallery with content hashes, safe JSON caching and automatic refresh."""
import hashlib
import json
import logging
from pathlib import Path
import numpy as np
from .config import DATA_DIR

logger = logging.getLogger(__name__)

class FaceRecognizer:
    def __init__(self, cache_file=None, backend=None):
        if backend is None:
            import face_recognition
            backend = face_recognition
        self.backend = backend
        self.cache_file = Path(cache_file or DATA_DIR / "cache" / "face-encodings.json")
        self.known_face_encodings = []
        self.known_face_names = []
        self.warnings = []
        self._fingerprint = None
        try:
            self.cache = json.loads(self.cache_file.read_text(encoding="utf-8"))
            if not isinstance(self.cache, dict):
                self.cache = {}
        except (OSError, ValueError):
            self.cache = {}

    def load_known_faces(self, photo_dir, labels=None):
        labels = labels or {}
        directory = Path(photo_dir)
        paths = sorted(p for p in directory.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
        fingerprint = tuple((p.name, p.stat().st_mtime_ns, p.stat().st_size, labels.get(p.name, p.stem)) for p in paths)
        if fingerprint == self._fingerprint:
            return
        cache, encodings, names, warnings = {}, [], [], []
        for path in paths:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entry = self.cache.get(path.name, {})
            if not isinstance(entry, dict) or entry.get("hash") != digest:
                try:
                    image = self.backend.load_image_file(str(path))
                    locations = self.backend.face_locations(image, model="hog")
                    features = self.backend.face_encodings(image, known_face_locations=locations) if len(locations) == 1 else []
                    entry = {"hash": digest, "encoding": features[0].tolist() if features else None}
                except Exception as exc:
                    logger.warning("Cannot encode %s: %s", path.name, exc)
                    entry = {"hash": digest, "encoding": None}
            cache[path.name] = entry
            vector = entry.get("encoding")
            if vector is not None and np.asarray(vector).shape == (128,):
                encodings.append(np.asarray(vector, dtype=np.float64))
                names.append(labels.get(path.name, path.stem))
            else:
                warnings.append(path.name)
        self.cache, self.known_face_encodings, self.known_face_names = cache, encodings, names
        self.warnings, self._fingerprint = warnings, fingerprint
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.cache_file.with_suffix(".tmp")
        temp.write_text(json.dumps(cache), encoding="utf-8")
        temp.replace(self.cache_file)

    def identify(self, encoding, tolerance=0.48):
        if not self.known_face_encodings:
            return "Unknown", 0.0
        distances = self.backend.face_distance(self.known_face_encodings, encoding)
        best = int(np.argmin(distances))
        distance = float(distances[best])
        return (self.known_face_names[best], max(0.0, 1.0-distance)) if distance <= tolerance else ("Unknown", 0.0)

    def recognize(self, face_image):
        features = self.backend.face_encodings(np.ascontiguousarray(face_image[:, :, ::-1]))
        return self.identify(features[0]) if features else ("Unknown", 0.0)
