import json, os
from datetime import datetime
from typing import Optional

MEMORY_DIR = os.environ.get("NEURO_CHILD_MEMORY", "memory")

class Memory:
    def __init__(self, name: str = "default"):
        self.name = name
        os.makedirs(MEMORY_DIR, exist_ok=True)
        self.long_path = os.path.join(MEMORY_DIR, f"{name}_long.json")
        self.work_path = os.path.join(MEMORY_DIR, f"{name}_working.json")
        self.long: list[dict] = self._load(self.long_path)
        self.working: list[dict] = self._load(self.work_path)

    def _load(self, path: str) -> list[dict]:
        if not os.path.exists(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _save(self, path: str, data: list[dict]) -> None:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)

    def add(self, text: str, kind: str = "fact", importance: float = 0.5, ttl_hours: Optional[float] = None) -> dict:
        entry = {
            "id": datetime.utcnow().isoformat() + "Z",
            "kind": kind,  # fact | preference | lesson | event | skill
            "text": text,
            "importance": float(importance),
            "created": datetime.utcnow().isoformat() + "Z",
            "expires": (datetime.utcnow().timestamp() + ttl_hours * 3600) if ttl_hours else None,
        }
        self.long.append(entry)
        self._save(self.long_path, self.long)
        return entry

    def add_working(self, text: str, ttl_minutes: float = 30.0) -> dict:
        return self.add(text, kind="working", importance=0.3, ttl_hours=ttl_minutes / 60.0)

    def recall(self, query: str, k: int = 20) -> list[dict]:
        q = query.lower()
        scored = []
        for entry in self.long:
            if entry.get("expires") and datetime.utcnow().timestamp() > entry["expires"]:
                continue
            score = (entry.get("importance", 0.0) * 3.0) + (1.0 if q in entry.get("text", "").lower() else 0.0)
            scored.append((score, entry))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:k]]

    def compact(self, keep: int = 2000) -> None:
        kept = sorted(
            [e for e in self.long if not e.get("expires") or datetime.utcnow().timestamp() <= e["expires"]],
            key=lambda e: e.get("importance", 0.0),
            reverse=True,
        )[:keep]
        self.long = kept
        self._save(self.long_path, self.long)
