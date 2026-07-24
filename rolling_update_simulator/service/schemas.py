"""Request/response models for the rollout HTTP API.

Kept separate from `models.py` on purpose: these are wire-format DTOs (what a
client sends/receives over JSON), not the domain types the engine and
cluster operate on. Translating between the two happens in `app.py`.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, Field

HealthCheckMode = Literal["always_healthy", "fail_new_version"]


class RolloutConfigIn(BaseModel):
    desired_replicas: int = Field(..., gt=0)
    max_surge: int = Field(default=1, ge=0)
    max_unavailable: int = Field(default=0, ge=0)
    resource_capacity: Optional[int] = Field(default=None, ge=0)
    max_new_version_failures: int = Field(default=3, ge=0)


class ClusterConfigIn(BaseModel):
    startup_ticks: int = Field(default=1, ge=0)
    shutdown_ticks: int = Field(default=1, ge=0)
    health_check_mode: HealthCheckMode = "always_healthy"


class CreateRolloutRequest(BaseModel):
    old_version: str
    new_version: str
    config: RolloutConfigIn
    cluster: ClusterConfigIn = ClusterConfigIn()
    # Instances seeded as READY on old_version before the first tick.
    # Defaults to config.desired_replicas (a fleet already at steady state).
    seed_count: Optional[int] = Field(default=None, ge=0)


class InstanceOut(BaseModel):
    id: int
    version: str
    state: str
    ticks_in_state: int


class ActionOut(BaseModel):
    type: str
    version: Optional[str] = None
    instance_id: Optional[int] = None


class RolloutSummary(BaseModel):
    id: str
    old_version: str
    new_version: str
    status: str
    tick: int
    active_count: int
    ready_count: int


class RolloutDetail(RolloutSummary):
    config: RolloutConfigIn
    instances: List[InstanceOut]


class TickResult(BaseModel):
    tick: int
    status_before: str
    status_after: str
    actions: List[ActionOut]
    instances: List[InstanceOut]
    active_count: int
    ready_count: int


class RunResult(BaseModel):
    settled: bool
    final_status: str
    ticks_run: int
    log: List[TickResult]
