"""NeuroGrip dashboard: Flask + Socket.IO. Run: python app.py  (NG_MODE=camera default | mock | hardware)."""
import logging
import os
import secrets
from pathlib import Path
import threading
import time
from collections import defaultdict, deque
from functools import wraps

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for
from flask_socketio import SocketIO, join_room

from neurogrip.agent import ToolBox, make_nvidia_client, nemotron_model, run_agent
from neurogrip.detect import Detector
from neurogrip.engine import MODES, make_engine
from neurogrip.incidents import CATEGORIES, SEVERITIES, AuditLog, IncidentLog
from neurogrip.patient_view import explain_for_patient
from neurogrip.triage import (DEFAULT_THERAPISTS, ai_brief, seed_demo_patients, seed_population,
                              triage_patients, triage_population)

USERS = {"therapist": "therapist", "patient": "patient"}  # hackathon demo logins
log = logging.getLogger("neurogrip")
FAIL_WINDOW_S = 60
FAIL_ALERT, FAIL_LOCKOUT = 3, 5  # failed sign-ins per address per minute: open an incident / lock out
POPULATION = int(os.environ.get("NG_POPULATION", "1200"))


def isolated() -> bool:
    """NG_ISOLATED=1: air-gapped mode. No outbound AI calls; the server only listens on localhost."""
    return os.environ.get("NG_ISOLATED") == "1"


def no_ai_error():
    return jsonify(error="isolated mode: external AI disabled" if isolated() else "NVIDIA_API_KEY not set"), 503


SECRET_FILE = Path(__file__).resolve().parent / ".ng_secret"


def load_secret(path: Path = SECRET_FILE) -> str:
    """Session-signing key that survives restarts, so open tabs stay logged in (env NG_SECRET wins)."""
    if os.environ.get("NG_SECRET"):
        return os.environ["NG_SECRET"]
    try:
        return path.read_text().strip()
    except FileNotFoundError:
        key = secrets.token_hex(32)
        path.write_text(key)
        return key


def create_app(engine, start: bool = True):
    app = Flask(__name__)
    app.secret_key = load_secret()
    app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Strict")
    socketio = SocketIO(app, async_mode="threading")
    RESPONDERS = "responders"  # socket room: incident and audit traffic only reaches therapists

    incidents = IncidentLog(engine.store, on_change=lambda d: socketio.emit("incident", d, to=RESPONDERS))
    audit = AuditLog(engine.store, on_change=lambda r: socketio.emit("audit", r, to=RESPONDERS))
    detector = Detector(incidents, patient_id=engine.patient_id)
    engine.listeners.append(detector.on_event)
    app.extensions["ng"] = {"incidents": incidents, "audit": audit, "detector": detector}
    failed: dict[str, deque] = defaultdict(deque)
    population: dict = {}

    def actor() -> str:
        return session.get("role") or "anonymous"

    def ip() -> str:
        return request.remote_addr or "?"

    def ai_client():
        return None if isolated() else make_nvidia_client()

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        return resp

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
                audit.record(actor(), "denied", f"{request.method} {request.path}", ip())
                incidents.raise_incident(
                    "access_denied", "Unauthorized access attempt", "medium", "security",
                    {"account": actor(), "endpoint": request.path},
                    f"The '{actor()}' account called {request.method} {request.path}, which needs the therapist "
                    "role. Request blocked and logged.")
                return jsonify(error="therapist access only"), 403
            return fn(*a, **kw)
        return wrapper

    @app.route("/login", methods=["GET", "POST"])
    def login():
        error = None
        if request.method == "POST":
            now, addr = time.monotonic(), ip()
            fails = failed[addr]
            while fails and now - fails[0] > FAIL_WINDOW_S:
                fails.popleft()
            if len(fails) >= FAIL_LOCKOUT:
                wait = int(FAIL_WINDOW_S - (now - fails[0])) + 1
                audit.record(request.form.get("username", ""), "login_blocked", "locked out", addr)
                return render_template("login.html", error=f"Too many failed attempts. Try again in {wait} s."), 429
            user, pw = request.form.get("username", ""), request.form.get("password", "")
            if USERS.get(user) == pw:
                session.clear()
                session["role"] = user
                fails.clear()
                audit.record(user, "login", "signed in", addr)
                return redirect(url_for("dashboard"))
            fails.append(now)
            audit.record(user or "anonymous", "login_failed", "wrong username or password", addr)
            if len(fails) >= FAIL_ALERT:
                incidents.raise_incident(
                    "failed_logins", "Repeated failed sign-ins",
                    "critical" if len(fails) >= FAIL_LOCKOUT else "high", "security", {"source": addr},
                    f"{len(fails)} failed sign-ins from {addr} in the last minute (last username tried: "
                    f"'{user[:40]}'). Lockout after {FAIL_LOCKOUT}.")
            error = "Invalid username or password"
        return render_template("login.html", error=error)

    @app.route("/logout")
    def logout():
        if session.get("role"):
            audit.record(actor(), "logout", "signed out", ip())
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

    @app.post("/api/calibrate")
    @login_required
    def api_calibrate():
        engine.start_calibration()
        return jsonify(ok=True)

    @app.post("/api/control")
    @login_required
    def api_control():
        body = request.get_json(silent=True) or {}
        try:
            engine.set_control(body.get("mode"), body.get("grip"))
        except ValueError as e:
            return jsonify(error=str(e)), 400
        s = engine.state()
        return jsonify(control_mode=s["control_mode"], grip=s["grip"])

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
        client = ai_client()
        if client is None:
            return no_ai_error()
        audit.record(actor(), "agent_review", "Nemotron session review started", ip())
        try:
            result = run_agent(client, nemotron_model(), ToolBox(engine, incidents))
        except Exception as e:
            log.exception("agent failed")
            return jsonify(error=f"Nemotron call failed: {e}"), 502
        return jsonify(result)

    @app.get("/api/triage")
    @therapist_only
    def api_triage():
        client = ai_client()
        if client is None:
            return no_ai_error()
        try:
            caseload = engine.store.patients() or seed_demo_patients()  # seeded into MongoDB at startup
            return jsonify(patients=triage_patients(client, nemotron_model(), caseload))
        except Exception as e:
            log.exception("triage failed")
            return jsonify(error=f"triage failed: {e}"), 502

    def run_population() -> dict:
        if "result" not in population:
            res = triage_population(seed_population(POPULATION), DEFAULT_THERAPISTS)
            population["result"] = res
            s = res["summary"]
            if s["unassigned_urgent"]:
                incidents.raise_incident(
                    "capacity_gap", f"{s['unassigned_urgent']} urgent patients have no therapist", "high", "caseload",
                    {"network": "regional"},
                    f"{s['urgent']} of {s['total']} patients are urgent but therapist capacity is {s['capacity']}. "
                    f"Urgent coverage {s['urgent_coverage_pct']}%. The rest are waitlisted in risk order.")
        return population["result"]

    @app.get("/api/triage/population")
    @therapist_only
    def api_population():
        res = run_population()
        limit = max(1, min(len(res["patients"]), request.args.get("limit", 200, type=int)))
        tier = request.args.get("urgency")
        rows = [r for r in res["patients"] if tier in (None, "", r["urgency"])]
        return jsonify(summary=res["summary"], therapists=res["therapists"], patients=rows[:limit],
                       brief=population.get("brief"))

    @app.post("/api/triage/brief")
    @therapist_only
    def api_population_brief():
        client = ai_client()
        if client is None:
            return no_ai_error()
        res = run_population()
        try:
            out = ai_brief(client, nemotron_model(), res)
        except Exception as e:
            log.exception("population brief failed")
            return jsonify(error=f"Nemotron call failed: {e}"), 502
        for r in res["patients"]:
            if r["patient_id"] in out["reasons"]:
                r["ai_reason"] = out["reasons"][r["patient_id"]]
        population["brief"] = out["brief"]
        audit.record(actor(), "triage_brief", f"Nemotron coordination brief for {res['summary']['total']} patients",
                     ip())
        return jsonify(out)

    # --- incident command center ------------------------------------------------------------------
    @app.get("/api/incidents")
    @therapist_only
    def api_incidents():
        status = request.args.get("status") or None
        return jsonify(incidents=incidents.list(status), counts=incidents.counts())

    @app.post("/api/incidents")
    @therapist_only
    def api_declare_incident():
        body = request.get_json(silent=True) or {}
        title = str(body.get("title") or "").strip()[:120]
        severity, category = body.get("severity", "medium"), body.get("category", "clinical")
        if not title or severity not in SEVERITIES or category not in CATEGORIES:
            return jsonify(error=f"need a title, severity in {SEVERITIES}, category in {CATEGORIES}"), 400
        scope = {k: str(v)[:80] for k, v in (body.get("scope") or {"patient": engine.patient_id}).items() if v}
        inc = incidents.raise_incident(f"manual:{time.time_ns()}", title, severity, category, scope,
                                       str(body.get("detail") or "Declared by a responder.")[:500], actor=actor())
        audit.record(actor(), "incident_declared", f"{inc['id']} {title}", ip())
        return jsonify(inc)

    @app.post("/api/incidents/<iid>/<action>")
    @therapist_only
    def api_incident_action(iid, action):
        body = request.get_json(silent=True) or {}
        who = actor()
        try:
            if action == "ack":
                inc = incidents.acknowledge(iid, who)
            elif action == "assign":
                inc = incidents.assign(iid, str(body.get("owner") or who)[:40], who)
            elif action == "note":
                inc = incidents.note(iid, who, str(body.get("text") or ""))
            elif action == "resolve":
                inc = incidents.resolve(iid, who, str(body.get("text") or "")[:500])
            elif action == "reopen":
                inc = incidents.reopen(iid, who)
            elif action == "scope":
                inc = incidents.set_scope(iid, body.get("scope") or {}, who)
            else:
                return jsonify(error=f"unknown action {action}"), 404
        except KeyError:
            return jsonify(error=f"no incident {iid}"), 404
        except ValueError as e:
            return jsonify(error=str(e)), 400
        audit.record(who, f"incident_{action}", iid, ip())
        return jsonify(inc)

    @app.get("/api/audit")
    @therapist_only
    def api_audit():
        return jsonify(audit=audit.list(request.args.get("limit", 200, type=int)))

    @app.post("/api/patient_view")
    @login_required
    def api_patient_view():
        if isolated():
            return jsonify(error="isolated mode: external AI disabled"), 503
        try:
            history = engine.store.history(engine.patient_id, 1)
            return jsonify(text=explain_for_patient(engine.state(), history[0] if history else None))
        except RuntimeError as e:
            return jsonify(error=str(e)), 503
        except Exception as e:
            log.exception("gemini failed")
            return jsonify(error=f"Gemini call failed: {e}"), 502

    @socketio.on("connect")
    def on_connect(auth=None):
        if session.get("role") not in USERS:
            return False
        if session.get("role") == "therapist":
            join_room(RESPONDERS)
        return True

    def detect_loop():
        while True:
            socketio.sleep(1.0)
            try:
                detector.check(engine.state(), time.monotonic())
            except Exception:
                log.exception("detection check failed")

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
        socketio.start_background_task(detect_loop)
        try:  # MongoDB Atlas: keep patient profiles alongside sessions
            for p in seed_demo_patients():
                engine.store.upsert_patient(p)
        except Exception:
            log.exception("could not seed patients into the store")

    return app, socketio


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app, socketio = create_app(make_engine())
    socketio.run(app, host="127.0.0.1" if isolated() else "0.0.0.0", port=int(os.environ.get("PORT", "5000")), allow_unsafe_werkzeug=True)
