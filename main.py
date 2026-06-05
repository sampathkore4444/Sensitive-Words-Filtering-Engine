import os
import sys
import json
import logging
import urllib.request
import urllib.error

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config import AppConfig, config as app_config
from engine.pipeline import DetectionPipeline
from storage.word_list import WordListStore
from storage.reports import ReportStore
from api.detect import router as detect_router
from api.words import router as words_router
from api.reports import router as reports_router


def setup_logging(level: str = "info", fmt: str = "text"):
    log_level = getattr(logging, level.upper(), logging.INFO)
    if fmt == "json":
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(
            '{"time": "%(asctime)s", "level": "%(levelname)s", '
            '"module": "%(module)s", "message": "%(message)s"}'
        ))
        logging.basicConfig(level=log_level, handlers=[handler])
    else:
        logging.basicConfig(
            level=log_level,
            format="%(asctime)s [%(levelname)s] %(module)s: %(message)s",
        )


config_path = os.environ.get("CONFIG_PATH", "config.yaml")
if os.path.exists(config_path):
    try:
        loaded = AppConfig.from_yaml(config_path)
        app_config.server = loaded.server
        app_config.detection = loaded.detection
        app_config.word_list = loaded.word_list
        app_config.reporting = loaded.reporting
        app_config.logging = loaded.logging
    except Exception as e:
        print(f"Warning: Failed to load config from {config_path}: {e}")

setup_logging(app_config.logging.level, app_config.logging.format)
logger = logging.getLogger(__name__)


word_store = WordListStore(
    persist_path=os.environ.get("WORD_LIST_PATH", "data/word_list.json")
)
report_store = ReportStore(
    persist_path=os.environ.get("REPORT_PATH", "data/reports.jsonl"),
    retention_days=app_config.reporting.retention_days,
    webhook_url=app_config.reporting.webhook_url,
)
detection_pipeline = DetectionPipeline(config=app_config.detection)


def _initialize_word_list():
    default_path = app_config.word_list.default_path
    if os.path.exists(default_path):
        logger.info("Loading default word list from %s", default_path)
        word_store.load_from_txt(default_path)
    else:
        logger.warning("Default word list not found at %s", default_path)

    json_path = f"data/word_list.json"
    if os.path.exists(json_path):
        logger.info("Loading persisted word list from %s", json_path)
        word_store.load(json_path)

    entries = word_store.list_all()
    logger.info("Loaded %d words into pipeline", len(entries))
    detection_pipeline.load_words(entries)


app = FastAPI(
    title="Sensitive Words Filteration API",
    version="1.0.0",
    description="Real-time sensitive word detection with obfuscation bypass, "
                "fuzzy matching, and risk scoring.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _fire_webhook(report):
    webhook = app_config.reporting.webhook_url
    if not webhook:
        return
    try:
        data = json.dumps(report.to_dict(), ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(webhook, data=data,
                                     headers={"Content-Type": "application/json"},
                                     method="POST")
        urllib.request.urlopen(req, timeout=3)
    except Exception as e:
        logger.debug("Webhook call failed: %s", e)

if app_config.reporting.webhook_url:
    report_store.add_hook(_fire_webhook)

@app.on_event("startup")
async def startup():
    _initialize_word_list()
    logger.info(
        "Server starting on %s:%d with %d words loaded",
        app_config.server.host,
        app_config.server.port,
        detection_pipeline.ac.pattern_count,
    )


app.include_router(detect_router)
app.include_router(words_router)
app.include_router(reports_router)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "words_loaded": detection_pipeline.ac.pattern_count,
        "config": {
            "server": app_config.server.host + ":" + str(app_config.server.port),
            "detection": {
                "leetspeak": app_config.detection.leetspeak.enabled,
                "homoglyph": app_config.detection.homoglyph.enabled,
                "separator_bypass": app_config.detection.separator_bypass.enabled,
                "repetition": app_config.detection.repetition.enabled,
                "fuzzy": app_config.detection.fuzzy.enabled,
            },
        },
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=app_config.server.host,
        port=app_config.server.port,
        workers=app_config.server.workers,
        log_level=app_config.logging.level,
    )
