from typing import List, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Depends
from pydantic import BaseModel, Field

from models.word_entry import WordEntry
from storage.word_list import WordListStore
from config import config


router = APIRouter(prefix="/api/v1/words", tags=["Word List"])


class WordRequest(BaseModel):
    word: str = Field(..., min_length=1, max_length=config.word_list.max_word_length)
    base_score: float = Field(0.5, ge=0.0, le=1.0)
    tags: List[str] = []
    enabled: bool = True


class WordUpdateRequest(BaseModel):
    base_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    tags: Optional[List[str]] = None
    enabled: Optional[bool] = None


def get_store() -> WordListStore:
    from main import word_store
    return word_store


def get_pipeline():
    from main import detection_pipeline
    return detection_pipeline


@router.post("")
async def upload_words(
    req: List[WordRequest],
    store: WordListStore = Depends(get_store),
):
    if store.count() + len(req) > config.word_list.max_words:
        raise HTTPException(
            status_code=400,
            detail=f"Word list exceeds maximum of {config.word_list.max_words} words",
        )
    entries = []
    for item in req:
        entry = WordEntry(
            word=item.word,
            base_score=item.base_score,
            tags=item.tags,
            enabled=item.enabled,
        )
        entries.append(entry)
    added = store.add_many(entries)
    _reload_pipeline()
    return {
        "added": len(added),
        "total": store.count(),
        "words": store.to_dict(),
    }


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    store: WordListStore = Depends(get_store),
):
    content = await file.read()
    text = content.decode("utf-8")

    entries = []
    if file.filename and file.filename.endswith(".json"):
        import json
        data = json.loads(text)
        for item in data if isinstance(data, list) else [data]:
            entries.append(WordEntry(
                word=item.get("word", ""),
                base_score=item.get("base_score", 0.5),
                tags=item.get("tags", []),
                enabled=item.get("enabled", True),
            ))
    elif file.filename and file.filename.endswith(".csv"):
        import csv
        import io
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            tags = [t.strip() for t in row.get("tags", "").split(",") if t.strip()]
            entries.append(WordEntry(
                word=row.get("word", ""),
                base_score=float(row.get("base_score", 0.5)),
                tags=tags,
            ))
    else:
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                entries.append(WordEntry(word=line, base_score=0.5))

    valid = [e for e in entries if e.word]
    if not valid:
        raise HTTPException(status_code=400, detail="No valid words found in file")

    store.add_many(valid)
    _reload_pipeline()
    return {
        "added": len(valid),
        "total": store.count(),
        "filename": file.filename,
    }


@router.get("")
async def list_words(
    page: int = 1,
    page_size: int = 100,
    store: WordListStore = Depends(get_store),
):
    all_words = store.to_dict()
    start = (page - 1) * page_size
    end = start + page_size
    return {
        "total": len(all_words),
        "page": page,
        "page_size": page_size,
        "words": all_words[start:end],
    }


@router.get("/{word}")
async def get_word(word: str, store: WordListStore = Depends(get_store)):
    entry = store.get(word)
    if not entry:
        raise HTTPException(status_code=404, detail="Word not found")
    return {
        "id": entry.id,
        "word": entry.word,
        "base_score": entry.base_score,
        "tags": entry.tags,
        "enabled": entry.enabled,
    }


@router.post("/{word}")
async def add_single_word(
    word: str,
    req: WordRequest,
    store: WordListStore = Depends(get_store),
):
    entry = WordEntry(
        word=req.word or word,
        base_score=req.base_score,
        tags=req.tags,
        enabled=req.enabled,
    )
    store.add(entry)
    _reload_pipeline()
    return {"added": entry.word, "total": store.count()}


@router.put("/{word}")
async def update_word(
    word: str,
    req: WordUpdateRequest,
    store: WordListStore = Depends(get_store),
):
    updated = store.update(
        word=word,
        base_score=req.base_score,
        tags=req.tags,
        enabled=req.enabled,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Word not found")
    _reload_pipeline()
    return {
        "word": updated.word,
        "base_score": updated.base_score,
        "tags": updated.tags,
        "enabled": updated.enabled,
    }


@router.delete("")
async def clear_words(store: WordListStore = Depends(get_store)):
    store.clear()
    _reload_pipeline()
    return {"cleared": True, "total": 0}


@router.delete("/{word}")
async def delete_word(word: str, store: WordListStore = Depends(get_store)):
    deleted = store.delete(word)
    if not deleted:
        raise HTTPException(status_code=404, detail="Word not found")
    _reload_pipeline()
    return {"deleted": word, "total": store.count()}


@router.post("/reload")
async def reload_words(store: WordListStore = Depends(get_store)):
    store.load_from_txt(config.word_list.default_path)
    _reload_pipeline()
    return {"reloaded": True, "total": store.count()}


def _reload_pipeline():
    from main import detection_pipeline, word_store
    entries = word_store.list_all()
    detection_pipeline.load_words(entries)
