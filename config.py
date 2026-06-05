import yaml
import os
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class LeetspeakConfig:
    enabled: bool = True
    max_expansions: int = 1024


@dataclass
class HomoglyphConfig:
    enabled: bool = True
    use_unicode_confusables: bool = True


@dataclass
class SeparatorBypassConfig:
    enabled: bool = True
    separator_chars: List[str] = field(default_factory=lambda: [' ', '-', '.', '_', '/', '|', '~', '*', '!'])


@dataclass
class RepetitionConfig:
    enabled: bool = True
    collapse_threshold: int = 2


@dataclass
class FuzzyConfig:
    enabled: bool = True
    max_distance: int = 2
    min_word_length: int = 4
    distance_ratio: float = 0.25
    max_checks_per_message: int = 500


@dataclass
class ScoringTier:
    threshold: float = 0.0
    label: str = "low"
    action: str = "log"


@dataclass
class ScoringConfig:
    tiers: List[ScoringTier] = field(default_factory=lambda: [
        ScoringTier(threshold=0.3, label="low", action="log"),
        ScoringTier(threshold=0.6, label="medium", action="flag"),
        ScoringTier(threshold=0.8, label="high", action="warn"),
        ScoringTier(threshold=1.0, label="critical", action="block"),
    ])


@dataclass
class DetectionConfig:
    case_sensitive: bool = False
    default_base_score: float = 0.5
    max_message_length: int = 10000
    leetspeak: LeetspeakConfig = field(default_factory=LeetspeakConfig)
    homoglyph: HomoglyphConfig = field(default_factory=HomoglyphConfig)
    separator_bypass: SeparatorBypassConfig = field(default_factory=SeparatorBypassConfig)
    repetition: RepetitionConfig = field(default_factory=RepetitionConfig)
    fuzzy: FuzzyConfig = field(default_factory=FuzzyConfig)
    scoring: ScoringConfig = field(default_factory=ScoringConfig)


@dataclass
class WordListConfig:
    default_path: str = "./data/sensitive_words.txt"
    auto_reload: bool = False
    max_words: int = 100000
    max_word_length: int = 256


@dataclass
class ReportingConfig:
    storage: str = "memory"
    retention_days: int = 90
    webhook_url: str = ""
    stream: dict = field(default_factory=lambda: {"enabled": False, "type": "", "url": ""})


@dataclass
class LoggingConfig:
    level: str = "info"
    format: str = "text"


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    workers: int = 1


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    detection: DetectionConfig = field(default_factory=DetectionConfig)
    word_list: WordListConfig = field(default_factory=WordListConfig)
    reporting: ReportingConfig = field(default_factory=ReportingConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @classmethod
    def from_yaml(cls, path: str) -> "AppConfig":
        if not os.path.exists(path):
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        return cls._from_dict(raw)

    @classmethod
    def _from_dict(cls, d: dict) -> "AppConfig":
        server_raw = d.get("server", {})
        detect_raw = d.get("detection", {})
        wordlist_raw = d.get("word_list", {})
        report_raw = d.get("reporting", {})
        log_raw = d.get("logging", {})

        def _tier(t):
            return ScoringTier(
                threshold=t.get("threshold", 0.0),
                label=t.get("label", "low"),
                action=t.get("action", "log"),
            )

        return cls(
            server=ServerConfig(
                host=server_raw.get("host", "0.0.0.0"),
                port=server_raw.get("port", 8080),
                workers=server_raw.get("workers", 1),
            ),
            detection=DetectionConfig(
                case_sensitive=detect_raw.get("case_sensitive", False),
                default_base_score=detect_raw.get("default_base_score", 0.5),
                max_message_length=detect_raw.get("max_message_length", 10000),
                leetspeak=LeetspeakConfig(
                    enabled=detect_raw.get("leetspeak", {}).get("enabled", True),
                    max_expansions=detect_raw.get("leetspeak", {}).get("max_expansions", 1024),
                ),
                homoglyph=HomoglyphConfig(
                    enabled=detect_raw.get("homoglyph", {}).get("enabled", True),
                    use_unicode_confusables=detect_raw.get("homoglyph", {}).get("use_unicode_confusables", True),
                ),
                separator_bypass=SeparatorBypassConfig(
                    enabled=detect_raw.get("separator_bypass", {}).get("enabled", True),
                    separator_chars=detect_raw.get("separator_bypass", {}).get("separator_chars",
                                                                              [' ', '-', '.', '_', '/', '|', '~', '*', '!']),
                ),
                repetition=RepetitionConfig(
                    enabled=detect_raw.get("repetition", {}).get("enabled", True),
                    collapse_threshold=detect_raw.get("repetition", {}).get("collapse_threshold", 2),
                ),
                fuzzy=FuzzyConfig(
                    enabled=detect_raw.get("fuzzy", {}).get("enabled", True),
                    max_distance=detect_raw.get("fuzzy", {}).get("max_distance", 2),
                    min_word_length=detect_raw.get("fuzzy", {}).get("min_word_length", 4),
                    distance_ratio=detect_raw.get("fuzzy", {}).get("distance_ratio", 0.25),
                    max_checks_per_message=detect_raw.get("fuzzy", {}).get("max_checks_per_message", 500),
                ),
                scoring=ScoringConfig(
                    tiers=[_tier(t) for t in detect_raw.get("scoring", {}).get("tiers", [
                        {"threshold": 0.3, "label": "low", "action": "log"},
                        {"threshold": 0.6, "label": "medium", "action": "flag"},
                        {"threshold": 0.8, "label": "high", "action": "warn"},
                        {"threshold": 1.0, "label": "critical", "action": "block"},
                    ])],
                ),
            ),
            word_list=WordListConfig(
                default_path=wordlist_raw.get("default_path", "./data/sensitive_words.txt"),
                auto_reload=wordlist_raw.get("auto_reload", False),
                max_words=wordlist_raw.get("max_words", 100000),
                max_word_length=wordlist_raw.get("max_word_length", 256),
            ),
            reporting=ReportingConfig(
                storage=report_raw.get("storage", "memory"),
                retention_days=report_raw.get("retention_days", 90),
                webhook_url=report_raw.get("webhook_url", ""),
                stream=report_raw.get("stream", {"enabled": False, "type": "", "url": ""}),
            ),
            logging=LoggingConfig(
                level=log_raw.get("level", "info"),
                format=log_raw.get("format", "text"),
            ),
        )


config: AppConfig = AppConfig()
