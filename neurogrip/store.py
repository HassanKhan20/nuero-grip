"""Session storage: MongoDB Atlas when MONGODB_URI is set, otherwise in memory."""
import copy
import logging
import os
import time
import uuid


class MemoryStore:
    def __init__(self):
        self._sessions: list[dict] = []
        self._events: list[dict] = []
        self._patients: dict[str, dict] = {}

    def save_session(self, doc: dict) -> str:
        doc = {**copy.deepcopy(doc), "_id": uuid.uuid4().hex, "saved_at": time.time()}
        self._sessions.append(doc)
        return doc["_id"]

    def history(self, patient_id: str, limit: int = 5) -> list[dict]:
        docs = [d for d in reversed(self._sessions) if d.get("patient_id") == patient_id]
        return copy.deepcopy(docs[:limit])

    def log_event(self, doc: dict) -> None:
        self._events.append(dict(doc))
        del self._events[:-5000]

    def patients(self) -> list[dict]:
        return list(self._patients.values())

    def upsert_patient(self, doc: dict) -> None:
        self._patients[doc["patient_id"]] = dict(doc)


class MongoStore:
    def __init__(self, uri: str):
        from pymongo import MongoClient

        client = MongoClient(uri, serverSelectionTimeoutMS=5000)
        client.admin.command("ping")  # fail fast at startup, not mid-session
        self.db = client["neurogrip"]

    def save_session(self, doc: dict) -> str:
        doc = {**doc, "saved_at": time.time()}
        return str(self.db.sessions.insert_one(doc).inserted_id)

    def history(self, patient_id: str, limit: int = 5) -> list[dict]:
        cur = self.db.sessions.find({"patient_id": patient_id}, {"_id": 0}).sort("saved_at", -1).limit(limit)
        return list(cur)

    def log_event(self, doc: dict) -> None:
        self.db.events.insert_one(dict(doc))

    def patients(self) -> list[dict]:
        return list(self.db.patients.find({}, {"_id": 0}))

    def upsert_patient(self, doc: dict) -> None:
        self.db.patients.replace_one({"patient_id": doc["patient_id"]}, doc, upsert=True)


def make_store() -> MemoryStore | MongoStore:
    uri = os.environ.get("MONGODB_URI")
    if not uri:
        return MemoryStore()
    try:
        return MongoStore(uri)
    except Exception as e:
        logging.getLogger(__name__).warning("MongoDB unavailable (%s); using in-memory store", e)
        return MemoryStore()
