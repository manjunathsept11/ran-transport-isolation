"""Pydantic models for the synthetic-data generation config.

The whole generator run is described by one :class:`GenConfig`. It is what the dashboard
Settings page edits, what presets serialise to, and what every generated dataset records
for reproducibility. The frontend Zod schema mirrors these models.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field, field_validator, model_validator

DistKind = Literal["normal", "lognormal", "beta", "uniform", "gamma", "constant"]

MORPHOLOGIES = ("dense_urban", "urban", "suburban", "rural")

IncidentClass = Literal["transport", "ran", "shared"]

TRANSPORT_KINDS = (
    "microwave_fade",
    "congested_backhaul",
    "sfp_errors",
    "queue_drops",
    "routing_flap",
    "mtu_blackhole",
    "fiber_degradation",
)
RAN_KINDS = (
    "sleeping_sector",
    "external_interference",
    "coverage_hole",
    "cell_overshoot",
    "prb_exhaustion",
    "vswr",
)
SHARED_KINDS = ("site_power_outage", "severe_weather", "transport_node_reload")
ALL_KINDS = TRANSPORT_KINDS + RAN_KINDS + SHARED_KINDS


class Distribution(BaseModel):
    """A named probability distribution with parameters, sampled via numpy."""

    kind: DistKind = "normal"
    params: dict[str, float] = Field(default_factory=dict)
    clip_min: float | None = None
    clip_max: float | None = None

    @model_validator(mode="after")
    def _check_params(self) -> Distribution:
        required: dict[str, tuple[str, ...]] = {
            "normal": ("mean", "sd"),
            "lognormal": ("mean", "sigma"),
            "beta": ("a", "b"),
            "uniform": ("low", "high"),
            "gamma": ("shape", "scale"),
            "constant": ("value",),
        }
        missing = [p for p in required[self.kind] if p not in self.params]
        if missing:
            raise ValueError(f"{self.kind} distribution missing params: {missing}")
        return self

    def sample(self, rng: np.random.Generator, size: int | tuple[int, ...] | None = None) -> Any:
        p = self.params
        if self.kind == "normal":
            out = rng.normal(p["mean"], p["sd"], size)
        elif self.kind == "lognormal":
            # params expressed on the natural scale: mean is the median, sigma the log-sd
            out = np.exp(rng.normal(np.log(p["mean"]), p["sigma"], size))
        elif self.kind == "beta":
            out = rng.beta(p["a"], p["b"], size)
        elif self.kind == "uniform":
            out = rng.uniform(p["low"], p["high"], size)
        elif self.kind == "gamma":
            out = rng.gamma(p["shape"], p["scale"], size)
        else:  # constant
            out = np.full(size, p["value"]) if size is not None else p["value"]
        if self.clip_min is not None or self.clip_max is not None:
            out = np.clip(out, self.clip_min, self.clip_max)
        return out

    @property
    def central(self) -> float:
        p = self.params
        return {
            "normal": p.get("mean", 0.0),
            "lognormal": p.get("mean", 1.0),
            "beta": p.get("a", 1) / max(p.get("a", 1) + p.get("b", 1), 1e-9),
            "uniform": 0.5 * (p.get("low", 0.0) + p.get("high", 1.0)),
            "gamma": p.get("shape", 1.0) * p.get("scale", 1.0),
            "constant": p.get("value", 0.0),
        }[self.kind]


def _mix_validator(v: dict[str, float]) -> dict[str, float]:
    total = sum(v.values())
    if total <= 0:
        raise ValueError("mix weights must sum to a positive number")
    return {k: w / total for k, w in v.items()}


class MarketConfig(BaseModel):
    n_sites: int = Field(1200, ge=50, le=10000)
    n_regions: int = Field(6, ge=1, le=30)
    region_mix: dict[str, float] = Field(
        default_factory=lambda: {f"R{i+1}": 1.0 for i in range(6)}
    )
    morphology_mix: dict[str, float] = Field(
        default_factory=lambda: {
            "dense_urban": 0.12,
            "urban": 0.33,
            "suburban": 0.35,
            "rural": 0.20,
        }
    )
    microwave_fraction: float = Field(0.28, ge=0.0, le=1.0)
    # geographic bounding box the market is scattered inside (synthetic, ~metro scale)
    lat_center: float = 17.4
    lon_center: float = 78.5
    span_deg: float = 1.4

    _norm_region = field_validator("region_mix")(_mix_validator)
    _norm_morph = field_validator("morphology_mix")(_mix_validator)

    @model_validator(mode="after")
    def _morph_keys(self) -> MarketConfig:
        bad = set(self.morphology_mix) - set(MORPHOLOGIES)
        if bad:
            raise ValueError(f"unknown morphologies: {bad}; allowed {MORPHOLOGIES}")
        return self


class FeedConfig(BaseModel):
    enabled: bool = True


class OoklaFeedConfig(FeedConfig):
    tests_per_site_busy_hour: Distribution = Distribution(
        kind="gamma", params={"shape": 2.0, "scale": 1.3}, clip_min=0
    )


class N3FeedConfig(FeedConfig):
    # individual flows are sampled; aggregates are always produced per cell per bin
    sampled_flows_per_cell_bin: Distribution = Distribution(
        kind="gamma", params={"shape": 1.5, "scale": 2.0}, clip_min=0
    )


class QoEFeedConfig(FeedConfig):
    sessions_per_site_busy_hour: Distribution = Distribution(
        kind="gamma", params={"shape": 2.5, "scale": 2.2}, clip_min=0
    )
    youtube_fraction: float = Field(0.65, ge=0, le=1)


class TwampFeedConfig(FeedConfig):
    pass


class SevOneFeedConfig(FeedConfig):
    pass


class FeedsConfig(BaseModel):
    ookla: OoklaFeedConfig = OoklaFeedConfig()
    n3: N3FeedConfig = N3FeedConfig()
    qoe: QoEFeedConfig = QoEFeedConfig()
    twamp: TwampFeedConfig = TwampFeedConfig()
    sevone: SevOneFeedConfig = SevOneFeedConfig()


class IncidentSpec(BaseModel):
    """One injected fault with a known class and signature - i.e. a ground-truth label."""

    id: str | None = None
    incident_class: IncidentClass = Field(alias="class")
    kind: str
    targets: Literal["auto"] | list[str] = "auto"
    n_targets: int = Field(1, ge=1, le=200)
    start_offset_hours: float = Field(24.0, ge=0)
    duration_hours: float = Field(6.0, gt=0)
    magnitude: float = Field(0.6, gt=0, le=1.0)
    # optional: restrict auto target selection
    region: str | None = None
    morphology: str | None = None

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _kind_matches_class(self) -> IncidentSpec:
        if self.kind not in ALL_KINDS:
            raise ValueError(f"unknown incident kind {self.kind!r}; allowed {ALL_KINDS}")
        by_class = {
            "transport": TRANSPORT_KINDS,
            "ran": RAN_KINDS,
            "shared": SHARED_KINDS,
        }
        if self.kind not in by_class[self.incident_class]:
            raise ValueError(
                f"kind {self.kind!r} is not valid for class {self.incident_class!r}"
            )
        return self


class AutoIncidentRates(BaseModel):
    """Poisson rates (events per week) for randomly scheduled incidents on top of the
    explicit list. Lets a preset say 'a realistic mix' without enumerating every fault."""

    transport_per_week: float = 0.0
    ran_per_week: float = 0.0
    shared_per_week: float = 0.0
    # magnitude / duration draws for auto incidents
    magnitude: Distribution = Distribution(
        kind="beta", params={"a": 2.5, "b": 2.5}, clip_min=0.15, clip_max=0.95
    )
    duration_hours: Distribution = Distribution(
        kind="lognormal", params={"mean": 5.0, "sigma": 0.7}, clip_min=0.5, clip_max=72
    )
    transport_targets: Distribution = Distribution(
        kind="gamma", params={"shape": 3.0, "scale": 2.5}, clip_min=1, clip_max=40
    )


DEFAULT_METRIC_BASELINES: dict[str, Distribution] = {
    # radio
    "rsrp_dbm": Distribution(kind="normal", params={"mean": -95.0, "sd": 7.0}),
    "rsrq_db": Distribution(kind="normal", params={"mean": -11.0, "sd": 2.5}),
    # transport link (per hop)
    "link_base_delay_ms": Distribution(
        kind="lognormal", params={"mean": 1.6, "sigma": 0.5}, clip_min=0.2
    ),
    "link_base_jitter_ms": Distribution(
        kind="lognormal", params={"mean": 0.4, "sigma": 0.6}, clip_min=0.02
    ),
    "link_base_loss_pct": Distribution(
        kind="lognormal", params={"mean": 0.03, "sigma": 0.8}, clip_min=0.0, clip_max=2.0
    ),
    "link_capacity_mbps": Distribution(
        kind="lognormal", params={"mean": 900.0, "sigma": 0.5}, clip_min=80
    ),
    # server-side / internet (site independent control)
    "tcp_server_rtt_ms": Distribution(kind="normal", params={"mean": 22.0, "sd": 4.0}, clip_min=3),
    # demand
    "site_busy_hour_erlangs": Distribution(
        kind="lognormal", params={"mean": 55.0, "sigma": 0.55}, clip_min=3
    ),
}


class GenConfig(BaseModel):
    """Top-level generation config."""

    name: str = "mixed_realistic"
    description: str = ""
    seed: int = 42
    topology_seed: int = 20240901
    start_date: date = date(2026, 8, 17)
    duration_days: int = Field(14, ge=1, le=45)
    bin_seconds: int = Field(300, ge=60, le=3600)

    market: MarketConfig = MarketConfig()
    feeds: FeedsConfig = FeedsConfig()
    metric_baselines: dict[str, Distribution] = Field(
        default_factory=lambda: {k: v.model_copy(deep=True) for k, v in DEFAULT_METRIC_BASELINES.items()}
    )
    incidents: list[IncidentSpec] = Field(default_factory=list)
    auto_incidents: AutoIncidentRates = AutoIncidentRates()

    model_config = {"validate_assignment": True}

    @model_validator(mode="after")
    def _fill_baselines(self) -> GenConfig:
        for k, v in DEFAULT_METRIC_BASELINES.items():
            self.metric_baselines.setdefault(k, v.model_copy(deep=True))
        return self

    # --- convenience ---------------------------------------------------------
    @property
    def n_bins(self) -> int:
        return int(self.duration_days * 24 * 3600 / self.bin_seconds)

    def baseline(self, metric: str) -> Distribution:
        return self.metric_baselines[metric]

    def to_yaml_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)
