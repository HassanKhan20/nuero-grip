"""NeuroGrip dashboard: Flask + Socket.IO. Run: python app.py  (NG_MODE=camera default | mock | hardware)."""
import logging
import os
import secrets
import threading
import time
from functools import wraps

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for
from flask_socketio import SocketIO

from neurogrip.agent import ToolBox, make_nvidia_client, nemotron_model, run_agent
from neurogrip.engine import MODES, make_engine
from neurogrip.patient_view import explain_for_patient
from neurogrip.triage import seed_demo_patients, triage_patients

USERS = {"therapist": "therapist", "patient": "patient"}  # hackathon demo logins
log = logging.getLogger("neurogrip")


def create_app(engine, start: bool = True):
    app = Flask(__name__)
    app.secret_key = os.environ.get("NG_SECRET", secrets.token_hex(16))
    socketio = SocketIO(app, async_mode="threading")
    last_agent = {"summary": ""}

    def login_required(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if session.get("role") not in USERS:
                if request.path.startswith("/api/"):
                    return jsonify(error="login required"), 401
                return redirect(url_for("login"))
            return fn(*a, **kw)
        return wrapper

    def therapist_only(fn):
        @wraps(fn)
        @login_required
        def wrapper(*a, **kw):
            if session.get("role") != "therapist":
                return jsonify(error="therapist access only"), 403
            return fn(*a, **kw)
        return wrapper

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            user, pw = request.form.get("username", ""), request.form.get("password", "")
            if USERS.get(user) == pw:
                session["role"] = user
                return redirect(url_for("dashboard"))
            error = "Invalid username or password"
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def dashboard():
        return render_template("dashboard.html", role=session["role"], modes=MODES)

    @app.get("/api/state")
    @login_required
    def api_state():
        return jsonify(engine.state())

    @app.post("/api/mode")
    @login_required
    def api_mode():
        mode = (request.get_json(silent=True) or {}).get("mode")
        if mode not in MODES:
            return jsonify(error=f"mode must be one of {MODES}"), 400
        engine.set_mode(mode)
        return jsonify(mode=mode)

    @app.post("/api/difficulty")
    @therapist_only
    def api_difficulty():
        level = (request.get_json(silent=True) or {}).get("level")
        if not isinstance(level, int):
            return jsonify(error="level must be an integer 1-5"), 400
        return jsonify(level=engine.set_difficulty(level))

    @app.post("/api/latency")
    @therapist_only
    def api_latency():
        engine.cue_latency()
        return jsonify(ok=True)

    @app.post("/api/tapping")
    @therapist_only
    def api_tapping():
        seconds = (request.get_json(silent=True) or {}).get("seconds", 10)
        engine.start_tapping_test(max(3.0, min(30.0, float(seconds))))
        return jsonify(ok=True)

    @app.post("/api/intent")
    @login_required
    def api_intent():
        if engine.kind == "hardware":
            return jsonify(error="intent comes from the headband in hardware mode"), 400
        engine.control.held = bool((request.get_json(silent=True) or {}).get("held"))
        return jsonify(held=engine.control.held)

    @app.post("/api/intent/auto")
    @login_required
    def api_intent_auto():
        if engine.kind == "hardware":
            return jsonify(error="intent comes from the headband in hardware mode"), 400
        engine.control.auto = bool((request.get_json(silent=True) or {}).get("auto"))
        return jsonify(auto=engine.control.auto)

    @app.get("/video_feed")
    @login_required
    def video_feed():
        if engine.vision.jpeg() is None and not getattr(engine.vision, "available", False):
            return jsonify(error="no camera in this mode"), 404

        def frames():
            boundary = b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
            while True:
                jpg = engine.vision.jpeg()
                if jpg:
                    yield boundary + jpg + b"\r\n"
                time.sleep(1 / 15)

        return Response(frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

    @app.post("/api/session/end")
    @therapist_only
    def api_end_session():
        try:
            return jsonify(session_id=engine.end_session())
        except Exception as e:
            log.exception("saving session failed")
            return jsonify(error=f"could not save session: {e}"), 502

    @app.post("/api/agent")
    @therapist_only
    def api_agent():
        client = make_nvidia_client()
        if client is None:
            return jsonify(error="NVIDIA_API_KEY not set"), 503
        try:
            result = run_agent(client, nemotron_model(), ToolBox(engine))
        except Exception as e:
            log.exception("agent failed")
            return jsonify(error=f"Nemotron call failed: {e}"), 502
        last_agent["summary"] = result["summary"]
        return jsonify(result)

    @app.get("/api/triage")
    @therapist_only
    def api_triage():
        client = make_nvidia_client()
        if client is None:
            return jsonify(error="NVIDIA_API_KEY not set"), 503
        try:
            return jsonify(patients=triage_patients(client, nemotron_model(), seed_demo_patients()))
        except Exception as e:
            log.exception("triage failed")
            return jsonify(error=f"triage failed: {e}"), 502

    @app.post("/api/patient_view")
    @login_required
    def api_patient_view():
        try:
            return jsonify(text=explain_for_patient(engine.state(), last_agent["summary"]))
        except RuntimeError as e:
            return jsonify(error=str(e)), 503
        except Exception as e:
            log.exception("gemini failed")
            return jsonify(error=f"Gemini call failed: {e}"), 502

    @socketio.on("connect")
    def on_connect(auth=None):
        return session.get("role") in USERS

    def broadcast():
        while True:
            socketio.sleep(0.1)
            try:
                socketio.emit("state", engine.state())
            except Exception:
                log.exception("state broadcast failed")

    engine.listeners.append(lambda e: socketio.emit("event", e))  # events (cue, incidents) go out instantly

    if start:
        stop = threading.Event()
        threading.Thread(target=engine.run_forever, args=(stop,), daemon=True).start()
        socketio.start_background_task(broadcast)
        try:  # MongoDB Atlas: keep patient profiles alongside sessions
            for p in seed_demo_patients():
                engine.store.upsert_patient(p)
        except Exception:
            log.exception("could not seed patients into the store")

    return app, socketio


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app, socketio = create_app(make_engine())
    socketio.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), allow_unsafe_werkzeug=True)
