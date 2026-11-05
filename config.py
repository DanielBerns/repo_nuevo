"""Configuration management for ArgenPrecios using Pydantic v2 and pathlib.Path."""

from __future__ import annotations

import logging
import os
import secrets
from datetime import date
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

logger = logging.getLogger(__name__)

DEFAULT_WORKDIR_RAW = "~/Info/ArgenPrecios"
DEFAULT_DEV_DATABASE_URL = (
    "postgresql+psycopg://argenprecios:argenprecios_dev@127.0.0.1:5433/argenprecios"
)


def resolve_user_path(raw: str | Path) -> Path:
    """Expand user home (~) and resolve to an absolute canonical Path."""
    return Path(raw).expanduser().resolve()


class DatabaseSettings(BaseModel):
    """PostgreSQL connection pool and timeout settings (credentials come from env)."""

    model_config = ConfigDict(extra="forbid")

    pool_size: int = Field(default=10, ge=1, le=100)
    max_overflow: int = Field(default=10, ge=0, le=100)
    statement_timeout_ms: int = Field(default=120_000, ge=1_000)
    echo_sql: bool = False


class SourcesSettings(BaseModel):
    """Read-only external producer directories and owned ArgenPrecios staging directories."""

    model_config = ConfigDict(extra="forbid")

    sur_en_precios_raw_dir: Path = Field(
        default_factory=lambda: resolve_user_path("~/Info/sur_en_precios/data/raw")
    )
    pipeline_price_scrape_samples_dir: Path = Field(
        default_factory=lambda: resolve_user_path(
            "~/Projects/github/DanielBerns/pipeline_price_scrape/samples"
        )
    )
    hermes_clean_db_path: Path = Field(
        default_factory=lambda: resolve_user_path(
            "~/Projects/github/DanielBerns/hermes_reborn/hermes_clean.db"
        )
    )
    fallback_sepa_raw_dir: Path = Field(
        default_factory=lambda: resolve_user_path("~/Info/ArgenPrecios/data/raw/sepa")
    )
    web_scrape_jsonl_dir: Path = Field(
        default_factory=lambda: resolve_user_path("~/Info/ArgenPrecios/data/raw/web_jsonl")
    )
    offline_surveys_dir: Path = Field(
        default_factory=lambda: resolve_user_path("~/Info/ArgenPrecios/data/raw/surveys")
    )
    offline_macro_dir: Path = Field(
        default_factory=lambda: resolve_user_path("~/Info/ArgenPrecios/data/raw/macro")
    )
    temp_extract_dir: Path = Field(
        default_factory=lambda: resolve_user_path("~/Info/ArgenPrecios/data/tmp")
    )
    sepa_portal_url: str = "https://datos.produccion.gob.ar/dataset/sepa-precios"

    @field_validator(
        "sur_en_precios_raw_dir",
        "pipeline_price_scrape_samples_dir",
        "hermes_clean_db_path",
        "fallback_sepa_raw_dir",
        "web_scrape_jsonl_dir",
        "offline_surveys_dir",
        "offline_macro_dir",
        "temp_extract_dir",
        mode="before",
    )
    @classmethod
    def _normalize_path(cls, value: str | Path) -> Path:
        return resolve_user_path(value)


class SpanSettings(BaseModel):
    """Parameters governing temporal price_spans compression and 500 GB storage guardrails."""

    model_config = ConfigDict(extra="forbid")

    max_bridge_gap_days: int = Field(default=2, ge=0, le=14)
    upsert_batch_size: int = Field(default=10_000, ge=100, le=100_000)
    hot_partition_fillfactor: int = Field(default=85, ge=50, le=100)
    precreate_quarters_ahead: int = Field(default=2, ge=1, le=8)
    storage_budget_gb: int = Field(default=500, ge=10)
    compaction_warning_threshold_gb: int = Field(default=380, ge=5)


def _default_repo_config_file(filename: str) -> Path:
    repo_root = Path(__file__).resolve().parents[2]
    return (repo_root / "config" / filename).resolve()


class AnalyticsSettings(BaseModel):
    """Paths and constants for regional weights, presidential periods, and CPI base index."""

    model_config = ConfigDict(extra="forbid")

    regional_weights_path: Path = Field(
        default_factory=lambda: _default_repo_config_file("regional_weights.yaml")
    )
    government_periods_path: Path = Field(
        default_factory=lambda: _default_repo_config_file("government_periods.yaml")
    )
    base_index_value: float = Field(default=100.0, gt=0.0)

    @field_validator("regional_weights_path", "government_periods_path", mode="before")
    @classmethod
    def _normalize_path(cls, value: str | Path) -> Path:
        return resolve_user_path(value)


class WebSettings(BaseModel):
    """Intranet FastAPI server settings (isolated on port 8080 from sur_en_precios)."""

    model_config = ConfigDict(extra="forbid")

    host: str = "127.0.0.1"
    port: int = Field(default=8080, ge=1024, le=65535)
    session_cookie_name: str = "argenprecios_session"
    session_max_age_seconds: int = Field(default=43_200, ge=300)
    allow_lan_read_access: bool = True


class AppConfig(BaseModel):
    """Top-level validated application configuration."""

    model_config = ConfigDict(extra="forbid")

    workdir: Path = Field(default_factory=lambda: resolve_user_path(DEFAULT_WORKDIR_RAW))
    database_url: str = Field(default=DEFAULT_DEV_DATABASE_URL, repr=False)
    secret_key: str = Field(default_factory=lambda: secrets.token_hex(32), repr=False)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    sources: SourcesSettings = Field(default_factory=SourcesSettings)
    spans: SpanSettings = Field(default_factory=SpanSettings)
    analytics: AnalyticsSettings = Field(default_factory=AnalyticsSettings)
    web: WebSettings = Field(default_factory=WebSettings)

    @field_validator("workdir", mode="before")
    @classmethod
    def _normalize_workdir(cls, value: str | Path) -> Path:
        return resolve_user_path(value)

    @property
    def logs_dir(self) -> Path:
        return self.workdir / "logs"

    @property
    def reports_dir(self) -> Path:
        return self.workdir / "reports"

    def ensure_owned_directories(self) -> None:
        """Create only ArgenPrecios-owned directories; never touch external producer paths."""
        owned = (
            self.workdir,
            self.logs_dir,
            self.reports_dir,
            self.sources.fallback_sepa_raw_dir,
            self.sources.web_scrape_jsonl_dir,
            self.sources.offline_surveys_dir,
            self.sources.offline_macro_dir,
            self.sources.temp_extract_dir,
        )
        for directory in owned:
            directory.mkdir(parents=True, exist_ok=True)


class ProvinceWeightSpec(BaseModel):
    """Expenditure and population weights for a single ISO 3166-2:AR jurisdiction."""

    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    population_share: float = Field(gt=0.0, le=1.0)
    expenditure_share_within_region: float = Field(gt=0.0, le=1.0)


class RegionWeightSpec(BaseModel):
    """INDEC statistical region definition and constituent provinces."""

    model_config = ConfigDict(extra="forbid")

    code: str
    name: str
    expenditure_weight: float = Field(gt=0.0, le=1.0)
    provinces: list[ProvinceWeightSpec]


class RegionalWeightsConfig(BaseModel):
    """Validated national 6-region / 24-province weighting hierarchy."""

    model_config = ConfigDict(extra="forbid")

    version: str = "1.0"
    regions: list[RegionWeightSpec]

    def province_to_region_map(self) -> dict[str, str]:
        mapping: dict[str, str] = {}
        for region in self.regions:
            for prov in region.provinces:
                mapping[prov.code.upper()] = region.code.upper()
        return mapping

    def national_province_expenditure_weights(self) -> dict[str, float]:
        weights: dict[str, float] = {}
        for region in self.regions:
            for prov in region.provinces:
                weights[prov.code.upper()] = (
                    region.expenditure_weight * prov.expenditure_share_within_region
                )
        return weights


class GovernmentPeriodSpec(BaseModel):
    """Presidential administration or macroeconomic sub-period definition."""

    model_config = ConfigDict(extra="forbid")

    slug: str
    name: str
    administration_label: str
    start_date: date
    end_date: date
    period_kind: str = "presidential_term"
    notes: str | None = None


class GovernmentPeriodsConfig(BaseModel):
    """Collection of presidential terms for cross-government CPI analysis."""

    model_config = ConfigDict(extra="forbid")

    version: str = "1.0"
    periods: list[GovernmentPeriodSpec]


def load_regional_weights(path: Path) -> RegionalWeightsConfig:
    """Load and validate INDEC regional & provincial weights from YAML."""
    resolved = resolve_user_path(path)
    raw_data = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    return RegionalWeightsConfig.model_validate(raw_data)


def load_government_periods(path: Path) -> GovernmentPeriodsConfig:
    """Load and validate presidential administration periods from YAML."""
    resolved = resolve_user_path(path)
    raw_data = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    return GovernmentPeriodsConfig.model_validate(raw_data)


def load_config(
    config_path: str | Path | None = None,
    workdir: str | Path | None = None,
) -> AppConfig:
    """Load AppConfig using precedence: CLI args -> env vars -> ~/Info/ArgenPrecios/config.yaml."""
    env_workdir = os.getenv("ARGENPRECIOS_WORKDIR")
    effective_workdir = resolve_user_path(
        workdir if workdir is not None else (env_workdir or DEFAULT_WORKDIR_RAW)
    )

    candidate_config = (
        resolve_user_path(config_path)
        if config_path is not None
        else (effective_workdir / "config.yaml").resolve()
    )

    payload: dict[str, Any] = {}
    if candidate_config.is_file():
        loaded = yaml.safe_load(candidate_config.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            payload.update(loaded)
    elif config_path is not None:
        raise FileNotFoundError(f"Explicit configuration file not found: {candidate_config}")

    if workdir is not None or "workdir" not in payload:
        payload["workdir"] = effective_workdir
    else:
        resolved_wd = resolve_user_path(payload["workdir"])
        payload["workdir"] = resolved_wd

    # Re-anchor default owned subdirectories when a custom workdir is supplied and not overridden
    final_workdir = resolve_user_path(payload["workdir"])
    sources_dict: dict[str, Any] = dict(payload.get("sources") or {})
    default_owned_relatives = {
        "fallback_sepa_raw_dir": Path("data/raw/sepa"),
        "web_scrape_jsonl_dir": Path("data/raw/web_jsonl"),
        "offline_surveys_dir": Path("data/raw/surveys"),
        "offline_macro_dir": Path("data/raw/macro"),
        "temp_extract_dir": Path("data/tmp"),
    }
    for key, rel_path in default_owned_relatives.items():
        if key not in sources_dict:
            sources_dict[key] = (final_workdir / rel_path).resolve()
    payload["sources"] = sources_dict

    env_db_url = os.getenv("ARGENPRECIOS_DATABASE_URL")
    if env_db_url:
        payload["database_url"] = env_db_url

    env_secret = os.getenv("ARGENPRECIOS_SECRET_KEY")
    if env_secret:
        payload["secret_key"] = env_secret

    return AppConfig.model_validate(payload)


__all__ = [
    "DEFAULT_DEV_DATABASE_URL",
    "DEFAULT_WORKDIR_RAW",
    "AnalyticsSettings",
    "AppConfig",
    "DatabaseSettings",
    "GovernmentPeriodSpec",
    "GovernmentPeriodsConfig",
    "ProvinceWeightSpec",
    "RegionWeightSpec",
    "RegionalWeightsConfig",
    "SourcesSettings",
    "SpanSettings",
    "WebSettings",
    "load_config",
    "load_government_periods",
    "load_regional_weights",
    "resolve_user_path",
]
