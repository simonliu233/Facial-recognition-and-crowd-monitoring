# Repository contents

This repository contains the local FaceTech application, templates, local web
assets, runtime model files, automated tests and the synthetic validation video.

The following machine-specific or private files are intentionally excluded:

- Existing account/member databases and password hashes
- Enrollment photos, recognition records and face-encoding caches
- Local session keys, runtime settings and logs
- Old server certificate files and migration/database backups
- The Python virtual environment and IDE files

A fresh clone starts without an account or enrolled faces. Run the application,
register your own account, then add enrollment photos through the local UI.
The Admin account in the original working folder is not distributed.

The legacy 68-point shape-predictor file is not used by this local version and
is excluded. The Caffe age/gender, FER emotion and YOLOv8 runtime models remain
included so inference does not require downloading model weights.

The face integration test derives a temporary face crop from the installed
Ultralytics package's public demo asset. It does not require private enrollment
photos. Temporary test accounts and databases are created by pytest.

This version is based on the face_recognition project present in the original
working directory. The original deployment instructions referred to:
https://github.com/kenkwok521/face_recognition

Third-party components and model weights retain their original licensing.
The FER notice and license are in Python Page/models/.
