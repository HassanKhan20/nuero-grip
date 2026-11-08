"""Incident command center: detections become tracked incidents with scope, owner, status and a timeline.

Every change is persisted to the store (MongoDB when configured) and pushed to `on_change`, which the
dashboard uses to broadcast it live to every signed-in responder.
"""
import copy
import threading
import time
from typing import Callable

SEVERITIES = ["low", "medium", "high", "critical"]
STATUSES = ["open", "acknowledged", "resolved"]
CATEGORIES = ["clinical", "device", "security", "caseload"]


def _key(kind: str, scope: dict) -> str:
    return kind + "|" + "|".join(f"{k}={scope[k]}" for k in sorted(scope))


class IncidentLog:
    def __init__(self, store=None, on_change: Callable[[dict], None] | None = None):
        self.store = store
        self.on_change = on_change
        self._lock = threading.RLock()
        self._items: dict[str, dict] = {}
        loaded = []
        try:
            loaded = list(store.incidents()) if store is not None and hasattr(store, "incidents") else []
        except Exception:
            loaded = []
        for doc in loaded:
            self._items[doc["id"]] = doc
        self._seq = max((int(i.split("-")[1]) for i in self._items), default=1000)

    # --- queries -------------------------------------------------------------------------------
    def list(self, status: str | None = None) -> list[dict]:
        with self._lock:
            rows = [i for i in self._items.values() if status in (None, i["status"])]
            rows.sort(key=lambda i: (i["created"], i["id"]), reverse=True)
            return copy.deepcopy(rows)

    def get(self, incident_id: str) -> dict:
        with self._lock:
            if incident_id not in self._items:
                raise KeyError(incident_id)
            return copy.deepcopy(self._items[incident_id])

    def counts(self) -> dict:
        with self._lock:
            out = {s: 0 for s in STATUSES}
            for i in self._items.values():
                out[i["status"]] += 1
            out["active_critical"] = sum(1 for i in self._items.values()
                                         if i["status"] != "resolved" and i["severity"] == "critical")
            return out

    # --- detection side ------------------------------------------------------------------------
    def _active(self, key: str) -> dict | None:
        for i in self._items.values():
            if i["key"] == key and i["status"] != "resolved":
                return i
        return None

    def raise_incident(self, kind: str, title: str, severity: str, category: str, scope: dict,
                       detail: str, actor: str = "system") -> dict:
        """Open an incident, or re-detect an active one with the same kind and scope (no duplicates)."""
        if severity not in SEVERITIES:
            raise ValueError(f"severity must be one of {SEVERITIES}")
        scope = dict(scope or {})
        now = time.time()
        with self._lock:
            inc = self._active(_key(kind, scope))
            if inc is not None:
                inc["count"] += 1
                inc["last_seen"] = now
                if SEVERITIES.index(severity) > SEVERITIES.index(inc["severity"]):
                    inc["severity"] = severity
                    self._add(inc, actor, "escalated", f"Escalated to {severity}: {detail}")
                else:
                    inc["detail"] = detail
                    inc["updated"] = now
            else:
                self._seq += 1
                inc = {"id": f"INC-{self._seq}", "key": _key(kind, scope), "kind": kind, "title": title,
                       "severity": severity, "category": category, "scope": scope, "detail": detail,
                       "status": "open", "owner": None, "count": 1, "created": now, "updated": now,
                       "last_seen": now, "timeline": []}
                self._items[inc["id"]] = inc
                self._add(inc, actor, "detected", detail)
            return self._commit(inc)

    def auto_resolve(self, kind: str, scope: dict, text: str) -> dict | None:
        with self._lock:
            inc = self._active(_key(kind, dict(scope or {})))
            if inc is None:
                return None
            inc["status"] = "resolved"
            self._add(inc, "system", "resolved", text)
            return self._commit(inc)

    # --- responder side ------------------------------------------------------------------------
    def acknowledge(self, incident_id: str, actor: str) -> dict:
        return self._transition(incident_id, actor, "acknowledged", "acknowledged", f"Acknowledged by {actor}")

    def resolve(self, incident_id: str, actor: str, text: str = "") -> dict:
        return self._transition(incident_id, actor, "resolved", "resolved", text or f"Resolved by {actor}")

    def reopen(self, incident_id: str, actor: str) -> dict:
        return self._transition(incident_id, actor, "open", "reopened", f"Reopened by {actor}")

    def assign(self, incident_id: str, owner: str, actor: str) -> dict:
        with self._lock:
            inc = self._require(incident_id)
            inc["owner"] = owner
            self._add(inc, actor, "assigned", f"Assigned to {owner}")
            return self._commit(inc)

    def note(self, incident_id: str, actor: str, text: str) -> dict:
        text = (text or "").strip()[:500]
        if not text:
            raise ValueError("note is empty")
        with self._lock:
            inc = self._require(incident_id)
            self._add(inc, actor, "note", text)
            return self._commit(inc)

    def set_scope(self, incident_id: str, scope: dict, actor: str) -> dict:
        with self._lock:
            inc = self._require(incident_id)
            inc["scope"] = {**inc["scope"], **{k: str(v)[:80] for k, v in (scope or {}).items() if v}}
            self._add(inc, actor, "scope", "Scope: " + ", ".join(f"{k} {v}" for k, v in inc["scope"].items()))
            return self._commit(inc)

    # --- internals -----------------------------------------------------------------------------
    def _require(self, incident_id: str) -> dict:
        if incident_id not in self._items:
            raise KeyError(incident_id)
        return self._items[incident_id]

    def _transition(self, incident_id, actor, status, kind, text) -> dict:
        with self._lock:
            inc = self._require(incident_id)
            inc["status"] = status
            if status == "acknowledged" and not inc["owner"]:
                inc["owner"] = actor
            self._add(inc, actor, kind, text)
            return self._commit(inc)

    @staticmethod
    def _add(inc: dict, actor: str, kind: str, text: str) -> None:
        now = time.time()
        inc["timeline"].append({"t": now, "actor": actor, "kind": kind, "text": text})
        del inc["timeline"][:-100]
        inc["updated"] = now

    def _commit(self, inc: dict) -> dict:
        doc = copy.deepcopy(inc)
        if self.store is not None and hasattr(self.store, "upsert_incident"):
            try:
                self.store.upsert_incident(doc)
            except Exception:
                pass  # the live command center keeps working if the database is down
        if self.on_change:
            try:
                self.on_change(copy.deepcopy(doc))
            except Exception:
                pass
        return doc


class AuditLog:
    """Append-only record of who did what: sign-ins, denied requests, responder and AI actions."""

    def __init__(self, store=None, on_change: Callable[[dict], None] | None = None, keep: int = 2000):
        self.store, self.on_change, self.keep = store, on_change, keep
        self._rows: list[dict] = []
        self._lock = threading.Lock()

    def record(self, actor: str, action: str, detail: str = "", ip: str = "") -> dict:
        row = {"t": time.time(), "actor": actor or "anonymous", "action": action, "detail": detail, "ip": ip}
        with self._lock:
            self._rows.append(row)
            del self._rows[:-self.keep]
        if self.store is not None and hasattr(self.store, "log_audit"):
            try:
                self.store.log_audit(dict(row))
            except Exception:
                pass
        if self.on_change:
            try:
                self.on_change(dict(row))
            except Exception:
                pass
        return row

    def list(self, limit: int = 200) -> list[dict]:
        with self._lock:
            return [dict(r) for r in reversed(self._rows[-limit:])]
