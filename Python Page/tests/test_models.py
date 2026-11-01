"""Actual offline models and the complete enrollment/video API flow."""
import io
import os
from pathlib import Path
import sys

os.environ.setdefault("KERAS_BACKEND","torch")
os.environ.setdefault("YOLO_AUTOINSTALL","false")
BASE = Path(__file__).resolve().parents[1]
os.environ.setdefault("YOLO_CONFIG_DIR",str(BASE/"data/local/ultralytics"))
sys.path.insert(0,str(BASE))

def test_actual_offline_models_and_complete_workflow(tmp_path,monkeypatch):
    import cv2
    import numpy as np
    import requests
    import torch
    from app import create_app,db
    torch.set_num_threads(4)
    def no_remote_requests(*args,**kwargs):
        raise AssertionError("The local workflow must not make HTTP requests")
    monkeypatch.setattr(requests.sessions.Session,"request",no_remote_requests)
    app=create_app({
        "TESTING":True,"SECRET_KEY":"integration-only","WTF_CSRF_ENABLED":False,
        "SQLALCHEMY_DATABASE_URI":"sqlite:///"+(tmp_path/"users.db").as_posix(),
        "PHOTO_DIR":str(tmp_path/"photos"),"LOCAL_DATA_DIR":str(tmp_path/"local"),
        "ANALYTICS_DB":str(tmp_path/"analytics.db"),
    })
    try:
        client=app.test_client()
        assert client.post("/register",data={"username":"integration","password":"testpassword123"}).status_code==302
        assert client.post("/login",data={"username":"integration","password":"testpassword123"}).status_code==302
        # Public package demo data keeps the published test independent of
        # the user's private enrollment photos.
        from importlib.metadata import distribution
        import face_recognition
        source = distribution("ultralytics").locate_file("ultralytics/assets/zidane.jpg")
        image = cv2.imread(str(source))
        assert image is not None, "Ultralytics public demo asset is missing"
        rgb = np.ascontiguousarray(image[:, :, ::-1])
        locations = face_recognition.face_locations(rgb, model="hog")
        assert locations, "The public demo image must contain a detectable face"
        top, right, bottom, left = max(locations, key=lambda box: (box[2]-box[0])*(box[1]-box[3]))
        margin = round(max(right-left, bottom-top)*0.2)
        crop = image[max(0,top-margin):min(image.shape[0],bottom+margin),
                     max(0,left-margin):min(image.shape[1],right+margin)]
        encoded_ok, encoded_photo = cv2.imencode(".jpg", crop)
        assert encoded_ok
        photo = encoded_photo.tobytes()
        response=client.post("/upload",data={"name":"Demo Person","contact":"test-only","age":"30","gender":"Female","file":(io.BytesIO(photo),"person.jpg")})
        assert response.status_code==302
        response=client.post("/face/process_frame",data={"image":(io.BytesIO(photo),"face.jpg")})
        assert response.status_code==200,response.json
        face=response.json["faces"][0]
        assert face["name"]=="Demo Person"
        assert face["age"]!="Unknown" and face["gender"] in {"Male","Female"}
        assert response.json["emotion_available"] and face["emotion"]!="Unavailable"
        assert len(app.extensions["analytics"].get_records())==1
        with app.app_context():
            from app import Member
            member_id=Member.query.one().id
        assert client.post(f"/client/{member_id}",data={"name":"Renamed Person","contact":"x","age":"31","gender":"Female"}).status_code==302
        response=client.post("/face/process_frame",data={"image":(io.BytesIO(photo),"face.jpg")})
        assert response.json["faces"][0]["name"]=="Renamed Person"
        assert client.delete(f"/client/{member_id}").json["success"]
        response=client.post("/face/process_frame",data={"image":(io.BytesIO(photo),"face.jpg")})
        assert response.json["faces"][0]["name"]=="Unknown" and response.json["gallery_size"]==0
        blank=cv2.imencode(".jpg",np.zeros((480,640,3),np.uint8))[1].tobytes()
        assert client.post("/face/process_frame",data={"image":(io.BytesIO(blank),"blank.jpg")}).json["count"]==0

        cap=cv2.VideoCapture(str(BASE.parent/"validation/synthetic-crossing.webm"))
        events=[];count=0
        try:
            while True:
                ok,frame=cap.read()
                if not ok:break
                count+=1
                encoded=cv2.imencode(".jpg",frame)[1].tobytes()
                response=client.post("/flow/process_flow_frame",data={"image":(io.BytesIO(encoded),"frame.jpg"),"stream_id":"video-test","frame_index":str(count)})
                assert response.status_code==200,response.json
                events.extend(response.json["events"])
        finally:
            cap.release()
        assert count==80
        assert response.json["left_to_right"]==1 and response.json["right_to_left"]==1
        assert len(events)==2
        assert client.get("/flow/records").status_code==200
        conflict=client.post("/flow/process_flow_frame",data={"image":(io.BytesIO(blank),"blank.jpg"),"stream_id":"other","frame_index":"1"})
        assert conflict.status_code==409
        assert client.post("/flow/stop_camera",data={"stream_id":"video-test"}).status_code==200
        settings=client.post("/flow/settings",json={"axis":"y","line_position":0.6})
        assert settings.status_code==200
        assert client.get("/flow/get_current_stats").json["axis"]=="y"
        assert client.post("/flow/reset_counters").json["left_to_right"]==0
        assert client.post("/logout").status_code==302
        assert client.get("/face/").status_code==302
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()
