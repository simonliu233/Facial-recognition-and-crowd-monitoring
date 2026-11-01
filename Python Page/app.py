"""Single-origin local application; accounts, vision and records share port 5000."""
import os
import uuid
from pathlib import Path

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, send_from_directory, url_for
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, current_user, login_user, logout_user
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect, FlaskForm
from wtforms import PasswordField, StringField, SubmitField
from wtforms.validators import InputRequired, Length, ValidationError

from src.config import ANALYTICS_DB, DATA_DIR, LOGIN_DB, PHOTO_DIR, secret_key
from src.database_manager import DatabaseManager

db = SQLAlchemy()
bcrypt = Bcrypt()
login_manager = LoginManager()
csrf = CSRFProtect()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), nullable=False, unique=True)
    password = db.Column(db.String(128), nullable=False)
    members = db.relationship("Member", backref="user", lazy=True)

class Member(db.Model):
    __tablename__ = "member"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    contact = db.Column(db.String(100), nullable=False)
    age = db.Column(db.Integer, nullable=False)
    gender = db.Column(db.String(10), nullable=False)
    image_path = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

class RegisterForm(FlaskForm):
    username = StringField("使用者名稱", validators=[InputRequired(), Length(min=4, max=30)], filters=[lambda value: value.strip() if value else value])
    password = PasswordField("密碼", validators=[InputRequired(), Length(min=8, max=72)])
    submit = SubmitField("建立本機帳戶")

    def validate_username(self, field):
        if User.query.filter_by(username=field.data.strip()).first():
            raise ValidationError("這個使用者名稱已存在。")

    def validate_password(self, field):
        if len(field.data.encode("utf-8")) > 72:
            raise ValidationError("密碼的 UTF-8 長度不能超過 72 bytes。")

class LoginForm(FlaskForm):
    username = StringField("使用者名稱", validators=[InputRequired(), Length(max=30)], filters=[lambda value: value.strip() if value else value])
    password = PasswordField("密碼", validators=[InputRequired(), Length(max=128)])
    submit = SubmitField("登入")

@login_manager.user_loader
def load_user(user_id):
    try:
        return db.session.get(User, int(user_id))
    except (ValueError, TypeError):
        return None

def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=None, SQLALCHEMY_DATABASE_URI="sqlite:///" + LOGIN_DB.as_posix(),
        SQLALCHEMY_TRACK_MODIFICATIONS=False, MAX_CONTENT_LENGTH=8 * 1024 * 1024,
        PHOTO_DIR=str(PHOTO_DIR), LOCAL_DATA_DIR=str(DATA_DIR),
        ANALYTICS_DB=str(ANALYTICS_DB), SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)
    if not app.config["SECRET_KEY"]:
        app.config["SECRET_KEY"] = secret_key()
    Path(app.config["PHOTO_DIR"]).mkdir(parents=True, exist_ok=True)
    if app.config["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///"):
        Path(app.config["SQLALCHEMY_DATABASE_URI"][10:]).parent.mkdir(parents=True, exist_ok=True)
    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "login_page"
    csrf.init_app(app)
    with app.app_context():
        db.create_all()

    from main import FaceService, face_bp
    from flow_counter import FlowCounter, flow_bp
    analytics = DatabaseManager(app.config["ANALYTICS_DB"], import_archives=not app.testing)
    app.extensions["analytics"] = analytics
    app.extensions["face_service"] = FaceService(analytics, app.config["PHOTO_DIR"],
                                                Path(app.config["LOCAL_DATA_DIR"]) / "cache" / "face-encodings.json")
    app.extensions["flow_counter"] = FlowCounter(analytics, settings_path=Path(app.config["LOCAL_DATA_DIR"]) / "flow-settings.json")
    app.extensions["face_labels"] = lambda: {m.image_path: m.name for m in Member.query.all()}
    app.register_blueprint(face_bp, url_prefix="/face")
    app.register_blueprint(flow_bp, url_prefix="/flow")

    @app.before_request
    def require_local_login():
        if request.endpoint in {"home_page", "login_page", "register_page", "health", "static"}:
            return None
        if current_user.is_authenticated:
            return None
        if request.method != "GET" or request.accept_mimetypes.best == "application/json":
            return jsonify(error="請先登入本機帳戶。"), 401
        return redirect(url_for("login_page"))

    @app.errorhandler(413)
    def too_large(error):
        return jsonify(error="檔案超過 8 MB，請縮小圖片。"), 413

    @app.get("/health")
    def health():
        return jsonify(status="ok", mode="local", database="sqlite")

    @app.get("/")
    @app.get("/home")
    def home_page():
        return render_template("home.html")

    @app.route("/register", methods=["GET", "POST"])
    def register_page():
        form = RegisterForm()
        if form.validate_on_submit():
            user = User(username=form.username.data.strip(),
                        password=bcrypt.generate_password_hash(form.password.data).decode("utf-8"))
            db.session.add(user)
            db.session.commit()
            flash("帳戶已建立，請登入。")
            return redirect(url_for("login_page"))
        return render_template("register.html", form=form)

    @app.route("/login", methods=["GET", "POST"])
    def login_page():
        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter_by(username=form.username.data.strip()).first()
            try:
                valid = user is not None and bcrypt.check_password_hash(user.password, form.password.data)
            except ValueError:
                valid = False
            if valid:
                login_user(user, remember=request.form.get("remember") == "on")
                return redirect(url_for("face_page"))
            flash("使用者名稱或密碼錯誤。")
        return render_template("login.html", form=form)

    @app.post("/logout")
    def logout():
        logout_user()
        return redirect(url_for("home_page"))

    @app.get("/dashboard")
    @app.get("/face recognition")
    def face_page():
        members = Member.query.filter_by(user_id=current_user.id).all()
        return render_template("face.html", members=members,
                               counts=analytics.get_counts())

    @app.get("/get-data")
    def get_data():
        members = Member.query.filter_by(user_id=current_user.id).all()
        ages = [sum(lo <= m.age <= hi for m in members) for lo, hi in [(0,20),(21,40),(41,60),(61,130)]]
        return jsonify(totalMembers=len(members), ageLabels=["0–20","21–40","41–60","61+"], ageData=ages,
                       genderLabels=["Male","Female","Other"],
                       genderData=[sum(m.gender == gender for m in members) for gender in ("Male","Female","Other")])

    def member_fields():
        name, contact = request.form.get("name", request.form.get("mname", "")).strip(), request.form.get("contact", "").strip()
        try:
            age = int(request.form.get("age", ""))
        except ValueError:
            raise ValueError("年齡必須為整數。")
        gender = request.form.get("gender", "")
        if not name or len(name) > 100 or not contact or len(contact) > 100:
            raise ValueError("請提供姓名和聯絡資料（最多 100 字）。")
        if not 0 <= age <= 130 or gender not in {"Male","Female","Other"}:
            raise ValueError("請提供有效的年齡和性別。")
        return dict(name=name, contact=contact, age=age, gender=gender)

    @app.route("/upload", methods=["GET", "POST"])
    def upload():
        if request.method == "POST":
            path = None
            try:
                fields = member_fields()
                image_file = request.files.get("file")
                if image_file is None or not image_file.filename:
                    raise ValueError("請選擇一張包含單一正面人臉的照片。")
                import cv2
                import numpy as np
                import face_recognition
                raw = image_file.read()
                image = cv2.imdecode(np.frombuffer(raw, dtype=np.uint8), cv2.IMREAD_COLOR) if raw else None
                if image is None or image.shape[0] * image.shape[1] > 16_000_000:
                    raise ValueError("無效圖片或解析度過大。")
                locations = face_recognition.face_locations(np.ascontiguousarray(image[:,:,::-1]), model="hog")
                if len(locations) != 1:
                    raise ValueError(f"照片偵測到 {len(locations)} 張人臉；請選擇只有一人的清晰正面照片。")
                filename = uuid.uuid4().hex + ".jpg"
                path = Path(app.config["PHOTO_DIR"]) / filename
                if not cv2.imwrite(str(path), image):
                    raise ValueError("無法儲存圖片。")
                db.session.add(Member(**fields, image_path=filename, user_id=current_user.id))
                db.session.commit()
                flash("照片已加入，本機人臉資料會自動更新。")
                return redirect(url_for("clients"))
            except ValueError as exc:
                db.session.rollback()
                if path:
                    path.unlink(missing_ok=True)
                flash(str(exc))
                return render_template("upload.html"), 400
        return render_template("upload.html")

    @app.get("/clients")
    def clients():
        search = request.args.get("search", "").strip()
        query = Member.query.filter_by(user_id=current_user.id)
        if search:
            query = query.filter(Member.name.ilike("%" + search + "%"))
        return render_template("clients.html", members=query.order_by(Member.id.desc()).all(), search=search)

    @app.route("/client/<int:member_id>", methods=["GET", "POST", "DELETE"])
    def client_detail(member_id):
        member = db.get_or_404(Member, member_id)
        if member.user_id != current_user.id:
            abort(404)
        if request.method == "DELETE":
            filename = member.image_path
            db.session.delete(member)
            db.session.commit()
            if len(filename) == 36 and filename.endswith(".jpg"):
                (Path(app.config["PHOTO_DIR"]) / filename).unlink(missing_ok=True)
            return jsonify(success=True)
        if request.method == "POST":
            try:
                for key, value in member_fields().items():
                    setattr(member, key, value)
                db.session.commit()
                flash("資料已更新。")
                return redirect(url_for("clients"))
            except ValueError as exc:
                flash(str(exc))
                return render_template("client_detail.html", member=member), 400
        return render_template("client_detail.html", member=member)

    @app.get("/static/photo/<path:filename>")
    @app.get("/display/<path:filename>")
    def serve_photo(filename):
        return send_from_directory(app.config["PHOTO_DIR"], filename)

    @app.get("/detect")
    @app.get("/live")
    @app.get("/video_feed")
    def detect():
        return redirect(url_for("face.index"))

    @app.get("/setting")
    def user_settings():
        return render_template("setting.html")

    @app.post("/change-username")
    def change_username():
        value = request.form.get("new_username", "").strip()
        other = User.query.filter_by(username=value).first()
        if not 4 <= len(value) <= 30 or (other and other.id != current_user.id):
            flash("使用者名稱需為 4–30 字，且不能重複。")
        else:
            current_user.username = value
            db.session.commit()
            flash("使用者名稱已更新。")
        return redirect(url_for("user_settings"))

    @app.post("/change-password")
    def change_password():
        old, new = request.form.get("current_password", ""), request.form.get("new_password", "")
        if not 8 <= len(new) or len(new.encode("utf-8")) > 72:
            flash("新密碼需至少 8 字，且不超過 72 bytes。")
        elif not bcrypt.check_password_hash(current_user.password, old):
            flash("目前密碼錯誤。")
        else:
            current_user.password = bcrypt.generate_password_hash(new).decode("utf-8")
            db.session.commit()
            flash("密碼已更新。")
        return redirect(url_for("user_settings"))

    return app

if __name__ == "__main__":
    from run import main
    main()
