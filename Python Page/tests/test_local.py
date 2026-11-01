"""Regression tests use temporary storage and never alter the real accounts."""
import io
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.line_counter import LineCrossingCounter
from src.database_manager import DatabaseManager
from app import Member, User, bcrypt, create_app, db

def positions(counter, values, identity=1, start=0):
    events = []
    for i, value in enumerate(values):
        point = (value, 0.8) if counter.axis == "x" else (0.5, value)
        events.extend(counter.update([(identity, *point)], now=start+i*0.1))
    return events

def test_forward_return_and_multiple_passages():
    counter = LineCrossingCounter()
    events = positions(counter, [0.2,0.2,0.4,0.5,0.7,0.7,0.8,0.7,0.4,0.3,0.2,0.7,0.8])
    assert [e["direction"] for e in events] == ["left_to_right", "right_to_left", "left_to_right"]

def test_no_global_cooldown_for_a_crowd():
    counter = LineCrossingCounter()
    events = []
    for frame, x in enumerate([0.2,0.2,0.3,0.7,0.7]):
        events += counter.update([(i,x,0.8) for i in range(12)], now=frame*0.05)
    assert len(events) == 12
    assert len({e["event_id"] for e in events}) == 12

def test_both_directions_same_frame():
    counter = LineCrossingCounter()
    events = []
    for frame, x in enumerate([0.2,0.2,0.3,0.7,0.7]):
        events += counter.update([(1,x,0.8),(2,1-x,0.8)], now=frame*0.1)
    assert sorted(e["direction"] for e in events) == ["left_to_right","right_to_left"]

def test_deadband_jitter_does_not_count():
    counter = LineCrossingCounter()
    assert not positions(counter, [0.2,0.2,0.48,0.51,0.49,0.53,0.47,0.52,0.2,0.2])

def test_single_noisy_detection_is_not_a_crossing():
    counter = LineCrossingCounter()
    assert not positions(counter, [0.2,0.2,0.8,0.2,0.2,0.8,0.2])

def test_disappeared_track_is_not_extrapolated():
    counter = LineCrossingCounter()
    assert not positions(counter, [0.2,0.2,0.42])
    assert counter.update([], now=1) == []
    assert counter.update([], now=2) == []

def test_short_occlusion_same_identity_can_continue():
    counter = LineCrossingCounter()
    positions(counter, [0.2,0.2,0.3])
    counter.update([], now=1)
    events = positions(counter, [0.7,0.7], start=1.1)
    assert len(events) == 1

def test_expired_identity_does_not_bridge_a_long_gap():
    counter = LineCrossingCounter(max_idle=2)
    positions(counter, [0.2,0.2,0.3])
    assert not positions(counter, [0.7,0.7], start=8)

def test_skipped_middle_frames_still_allow_observed_crossing():
    assert len(positions(LineCrossingCounter(), [0.2,0.2,0.8,0.8])) == 1

def test_roi_excludes_people_outside_door():
    counter = LineCrossingCounter(roi=(0.3,0.7))
    assert not positions(counter, [0.2,0.2,0.8,0.8])
    assert len(counter.tracks) == 0

def test_roi_exit_clears_armed_state():
    counter = LineCrossingCounter(roi=(0.3,0.9))
    positions(counter, [0.2,0.2])
    counter.update([(1,0.5,0.1)], now=0.3)
    assert not positions(counter, [0.8,0.8], start=0.4)

def test_horizontal_crossing():
    events = positions(LineCrossingCounter(axis="y"), [0.2,0.2,0.8,0.8])
    assert len(events) == 1

@pytest.mark.parametrize("cfg", [
    {"axis":"z"}, {"position":float("nan")}, {"band":0},
    {"roi":(0.8,0.2)}, {"position":0.1,"band":0.15},
])
def test_invalid_counter_settings(cfg):
    with pytest.raises(ValueError):
        LineCrossingCounter(**cfg)

def test_storage_persists_and_deduplicates(tmp_path):
    path = tmp_path/"analytics.db"
    store = DatabaseManager(path, import_archives=False)
    event = {"event_id":"session:1","direction":"left_to_right","track_id":7}
    store.record_crossings([event,event])
    assert DatabaseManager(path, import_archives=False).get_counts()["left_to_right"] == 1
    assert store.add_record("Test","Happy",0.8)
    assert not store.add_record("Test","Happy",0.8)
    assert store.get_records()[0]["name"] == "Test"
    store.reset_counts()
    assert store.get_counts()["left_to_right"] == 0

def test_concurrent_events_are_not_lost(tmp_path):
    store = DatabaseManager(tmp_path/"analytics.db", import_archives=False)
    def record(i):
        store.record_crossings([{"event_id":str(i),"direction":"right_to_left","track_id":i}])
    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(record, range(30)))
    assert store.get_counts()["right_to_left"] == 30

@pytest.fixture
def application(tmp_path):
    app = create_app({
        "TESTING":True, "SECRET_KEY":"test-only", "WTF_CSRF_ENABLED":False,
        "SQLALCHEMY_DATABASE_URI":"sqlite:///" + (tmp_path/"accounts.db").as_posix(),
        "PHOTO_DIR":str(tmp_path/"photos"),"LOCAL_DATA_DIR":str(tmp_path/"local"),
        "ANALYTICS_DB":str(tmp_path/"analytics.db"),
    })
    yield app
    with app.app_context():
        db.session.remove()
        db.engine.dispose()

@pytest.fixture
def client(application):
    client = application.test_client()
    client.post("/register",data={"username":"tester","password":"password123"})
    client.post("/login",data={"username":"tester","password":"password123"})
    return client

def test_public_health_and_auth_redirect(application):
    client=application.test_client()
    assert client.get("/health").json["database"] == "sqlite"
    response=client.get("/clients")
    assert response.status_code == 302 and "/login" in response.location
    assert client.post("/face/process_frame").status_code == 401

def test_registration_and_duplicate_validation(application):
    client=application.test_client()
    assert client.post("/register",data={"username":"tester","password":"password123"}).status_code == 302
    response=client.post("/register",data={"username":"tester","password":"password123"})
    assert response.status_code == 200
    with application.app_context():
        assert User.query.count() == 1

@pytest.mark.parametrize("path", ["/","/dashboard","/clients","/upload","/setting","/face/","/face/records","/flow/","/flow/records"])
def test_pages_render_without_external_resources(client,path):
    response=client.get(path)
    assert response.status_code == 200
    assert b"https://" not in response.data
    assert b"http://" not in response.data
    assert b"data-port" not in response.data

def test_invalid_images_are_rejected_before_model_load(client):
    assert client.post("/face/process_frame").status_code == 400
    assert client.post("/flow/process_flow_frame",data={"image":(io.BytesIO(b"not an image"),"bad.jpg")}).status_code == 400
    assert client.post("/upload",data={"name":"Test","contact":"x","age":"20","gender":"Male","file":(io.BytesIO(b"bad"),"bad.jpg")}).status_code == 400

def test_settings_persistence_and_daily_reset(client,application):
    response=client.post("/flow/settings",json={"axis":"y","line_position":0.6,"dead_band":0.05,"roi_start":0.2,"roi_end":0.9})
    assert response.status_code == 200
    assert response.json["axis"] == "y"
    path=Path(application.config["LOCAL_DATA_DIR"])/"flow-settings.json"
    assert json.loads(path.read_text())["line_position"] == 0.6
    assert client.post("/flow/settings",json={"axis":"bad"}).status_code == 400
    assert client.post("/flow/reset_counters").json["left_to_right"] == 0

def test_account_changes_and_logout(client,application):
    assert client.post("/change-username",data={"new_username":"tester2"}).status_code == 302
    client.post("/change-password",data={"current_password":"password123","new_password":"newpassword123"})
    client.post("/logout")
    assert client.get("/dashboard").status_code == 302
    assert client.post("/login",data={"username":"tester2","password":"newpassword123"}).status_code == 302

def test_member_ownership(client,application):
    with application.app_context():
        other=User(username="other",password=bcrypt.generate_password_hash("password123").decode())
        db.session.add(other);db.session.flush()
        member=Member(name="Other",contact="x",age=20,gender="Other",image_path="none.jpg",user_id=other.id)
        db.session.add(member);db.session.commit()
        member_id=member.id
    assert client.get(f"/client/{member_id}").status_code == 404
    assert client.delete(f"/client/{member_id}").status_code == 404

def test_gallery_updates_modified_deleted_and_renamed_photos(tmp_path):
    import numpy as np
    from src.face_recognizer import FaceRecognizer
    class Backend:
        calls=0
        @staticmethod
        def load_image_file(path): return Path(path).read_bytes()
        @staticmethod
        def face_locations(image,**kwargs): return [(0,1,1,0)]
        def face_encodings(self,image,**kwargs):
            self.calls+=1
            return [np.ones(128)*image[0]]
    photos=tmp_path/"photos";photos.mkdir()
    path=photos/"person.jpg";path.write_bytes(b"A")
    backend=Backend()
    gallery=FaceRecognizer(tmp_path/"cache.json",backend)
    gallery.load_known_faces(photos,{"person.jpg":"Alice"})
    assert gallery.known_face_names == ["Alice"] and backend.calls == 1
    gallery.load_known_faces(photos,{"person.jpg":"New name"})
    assert gallery.known_face_names == ["New name"] and backend.calls == 1
    path.write_bytes(b"BB")
    gallery.load_known_faces(photos)
    assert backend.calls == 2 and gallery.known_face_encodings[0][0] == ord("B")
    path.unlink();gallery.load_known_faces(photos)
    assert gallery.known_face_names == []

@pytest.mark.parametrize("name", ["    ", " abc "])
def test_whitespace_cannot_bypass_username_length(application,name):
    client=application.test_client()
    response=client.post("/register",data={"username":name,"password":"password123"})
    assert response.status_code==200
    with application.app_context():
        assert User.query.count()==0
