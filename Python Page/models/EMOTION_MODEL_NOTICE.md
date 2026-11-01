# Local emotion model

emotion_model.hdf5 was copied from the already installed FER 22.5.1 package,
fer/data/emotion_model.hdf5 (872856 bytes).
Upstream: https://github.com/justinshenk/fer
The package license is included in FER-LICENSE.txt.

The model takes normalized 64 x 64 grayscale faces and returns seven scores:
Angry, Disgust, Fear, Happy, Sad, Surprise, Neutral.
It is an estimate of visible expression, not a validated measurement of a person's feelings.
No remote model download is performed.
