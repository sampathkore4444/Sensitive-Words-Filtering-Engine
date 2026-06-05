from dataclasses import dataclass, field
from typing import List, Optional
from datetime import datetime


@dataclass
class WordEntry:
    word: str
    normalized: str = ""
    base_score: float = 0.5
    tags: List[str] = field(default_factory=list)
    enabled: bool = True
    id: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    def __post_init__(self):
        if not self.normalized:
            import unicodedata
            self.normalized = unicodedata.normalize("NFKC", self.word).lower()
        now = datetime.utcnow()
        if self.created_at is None:
            self.created_at = now
        if self.updated_at is None:
            self.updated_at = now
