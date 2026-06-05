import json
import os
from typing import List, Optional, Dict, Any
from datetime import datetime
from models.word_entry import WordEntry


class WordListStore:
    def __init__(self, persist_path: Optional[str] = None):
        self._entries: Dict[str, WordEntry] = {}
        self._next_id = 1
        self.persist_path = persist_path

    def add(self, entry: WordEntry) -> WordEntry:
        key = entry.word.lower().strip()
        existing = self._entries.get(key)
        if existing:
            existing.base_score = entry.base_score
            existing.tags = entry.tags
            existing.enabled = entry.enabled
            existing.updated_at = datetime.utcnow()
            self._save()
            return existing
        entry.id = self._next_id
        self._next_id += 1
        self._entries[key] = entry
        self._save()
        return entry

    def add_many(self, entries: List[WordEntry]) -> List[WordEntry]:
        added = []
        for e in entries:
            added.append(self.add(e))
        return added

    def get(self, word: str) -> Optional[WordEntry]:
        return self._entries.get(word.lower().strip())

    def get_by_id(self, entry_id: int) -> Optional[WordEntry]:
        for entry in self._entries.values():
            if entry.id == entry_id:
                return entry
        return None

    def list_all(self) -> List[WordEntry]:
        return [e for e in self._entries.values() if e.enabled]

    def list_all_including_disabled(self) -> List[WordEntry]:
        return list(self._entries.values())

    def update(self, word: str, base_score: Optional[float] = None,
               tags: Optional[List[str]] = None, enabled: Optional[bool] = None) -> Optional[WordEntry]:
        entry = self.get(word)
        if not entry:
            return None
        if base_score is not None:
            entry.base_score = base_score
        if tags is not None:
            entry.tags = tags
        if enabled is not None:
            entry.enabled = enabled
        entry.updated_at = datetime.utcnow()
        self._save()
        return entry

    def delete(self, word: str) -> bool:
        key = word.lower().strip()
        if key in self._entries:
            del self._entries[key]
            self._save()
            return True
        return False

    def delete_by_id(self, entry_id: int) -> bool:
        for key, entry in list(self._entries.items()):
            if entry.id == entry_id:
                del self._entries[key]
                self._save()
                return True
        return False

    def clear(self):
        self._entries.clear()
        self._save()

    def count(self) -> int:
        return len(self._entries)

    def get_word_map(self) -> Dict[str, float]:
        return {e.word.lower(): e.base_score for e in self._entries.values() if e.enabled}

    def get_patterns(self) -> List[str]:
        return [e.word.lower() for e in self._entries.values() if e.enabled]

    def to_dict(self) -> List[Dict[str, Any]]:
        return [
            {
                "id": e.id,
                "word": e.word,
                "base_score": e.base_score,
                "tags": e.tags,
                "enabled": e.enabled,
                "created_at": e.created_at.isoformat() if e.created_at else None,
                "updated_at": e.updated_at.isoformat() if e.updated_at else None,
            }
            for e in self._entries.values()
        ]

    def _save(self):
        if not self.persist_path:
            return
        os.makedirs(os.path.dirname(self.persist_path), exist_ok=True)
        data = self.to_dict()
        with open(self.persist_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def load(self, path: str):
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for item in data:
            entry = WordEntry(
                word=item["word"],
                base_score=item.get("base_score", 0.5),
                tags=item.get("tags", []),
                enabled=item.get("enabled", True),
                id=item.get("id"),
                created_at=datetime.fromisoformat(item["created_at"]) if item.get("created_at") else None,
                updated_at=datetime.fromisoformat(item["updated_at"]) if item.get("updated_at") else None,
            )
            key = entry.word.lower().strip()
            self._entries[key] = entry
            if entry.id and entry.id >= self._next_id:
                self._next_id = entry.id + 1

    def load_from_txt(self, path: str, default_score: float = 0.5):
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#"):
                    self.add(WordEntry(word=line, base_score=default_score))
