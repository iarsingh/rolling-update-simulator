"""FastAPI microservice exposing the rollout engine over HTTP.

This is the same engine/cluster pair `simulator.py` drives locally, just
addressed by rollout id so many rollouts can be in flight at once, and
advanced by API calls (`/tick`, `/run`) instead of a local `while` loop.
See `rolling_update_simulator/service/README.md` for the endpoint reference
and the design doc's Low-Level Design section for the full contract.
"""

from __future__ import annotations

from typing import List

from fastapi import FastAPI, HTTPException

from ..cluster import Cluster, always_healthy
from ..engine import RolloutConfig, RolloutEngine
from ..models import Instance, InstanceState, RolloutStatus
from .schemas import (
    ActionOut,
    CreateRolloutRequest,
    InstanceOut,
    RolloutConfigIn,
    RolloutDetail,
    RolloutSummary,
    RunResult,
    TickResult,
)
from .store import Rollout, store

app = FastAPI(
    title="Rolling Update Simulator",
    summary="HTTP microservice for driving rolling-update rollouts.",
    version="1.0.0",
)

_SETTLED = (RolloutStatus.COMPLETE, RolloutStatus.ROLLED_BACK)


def _health_check_for(mode: str, new_version: str):
    if mode == "fail_new_version":
        return lambda instance: instance.version != new_version
    return always_healthy


def _instance_out(instance: Instance) -> InstanceOut:
    return InstanceOut(
        id=instance.id,
        version=instance.version,
        state=instance.state.value,
        ticks_in_state=instance.ticks_in_state,
    )


def _summary(rollout: Rollout) -> RolloutSummary:
    return RolloutSummary(
        id=rollout.id,
        old_version=rollout.engine.old_version,
        new_version=rollout.engine.new_version,
        status=rollout.engine.status.value,
        tick=rollout.tick,
        active_count=rollout.cluster.active_count(),
        ready_count=rollout.cluster.ready_count(),
    )


def _get_or_404(rollout_id: str) -> Rollout:
    rollout = store.get(rollout_id)
    if rollout is None:
        raise HTTPException(status_code=404, detail=f"no rollout with id {rollout_id!r}")
    return rollout


def _advance_one_tick(rollout: Rollout) -> TickResult:
    """The same four steps `simulator.run()` performs per iteration,
    scoped to a single tick and returned as a result instead of printed."""
    status_before = rollout.engine.status
    actions = rollout.engine.plan(rollout.cluster.instances)
    rollout.cluster.apply(actions)
    for instance in rollout.cluster.tick():
        rollout.engine.record_failure(instance)
    rollout.tick += 1

    return TickResult(
        tick=rollout.tick,
        status_before=status_before.value,
        status_after=rollout.engine.status.value,
        actions=[ActionOut(type=a.type.value, version=a.version, instance_id=a.instance_id) for a in actions],
        instances=[_instance_out(i) for i in rollout.cluster.instances],
        active_count=rollout.cluster.active_count(),
        ready_count=rollout.cluster.ready_count(),
    )


@app.post("/rollouts", response_model=RolloutDetail, status_code=201)
def create_rollout(request: CreateRolloutRequest) -> RolloutDetail:
    try:
        config = RolloutConfig(
            desired_replicas=request.config.desired_replicas,
            max_surge=request.config.max_surge,
            max_unavailable=request.config.max_unavailable,
            resource_capacity=request.config.resource_capacity,
            max_new_version_failures=request.config.max_new_version_failures,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    engine = RolloutEngine(config, old_version=request.old_version, new_version=request.new_version)
    cluster = Cluster(
        startup_ticks=request.cluster.startup_ticks,
        shutdown_ticks=request.cluster.shutdown_ticks,
        health_check=_health_check_for(request.cluster.health_check_mode, request.new_version),
    )

    seed_count = request.seed_count if request.seed_count is not None else config.desired_replicas
    for _ in range(seed_count):
        cluster.instances.append(Instance(version=request.old_version, state=InstanceState.READY))

    rollout = store.create(engine, cluster)
    return RolloutDetail(**_summary(rollout).model_dump(), config=request.config, instances=[_instance_out(i) for i in cluster.instances])


@app.get("/rollouts", response_model=List[RolloutSummary])
def list_rollouts() -> List[RolloutSummary]:
    return [_summary(r) for r in store.list()]


@app.get("/rollouts/{rollout_id}", response_model=RolloutDetail)
def get_rollout(rollout_id: str) -> RolloutDetail:
    rollout = _get_or_404(rollout_id)
    cfg = rollout.engine.config
    config = RolloutConfigIn(
        desired_replicas=cfg.desired_replicas,
        max_surge=cfg.max_surge,
        max_unavailable=cfg.max_unavailable,
        resource_capacity=cfg.resource_capacity,
        max_new_version_failures=cfg.max_new_version_failures,
    )
    return RolloutDetail(**_summary(rollout).model_dump(), config=config, instances=[_instance_out(i) for i in rollout.cluster.instances])


@app.delete("/rollouts/{rollout_id}", status_code=204)
def delete_rollout(rollout_id: str) -> None:
    if not store.delete(rollout_id):
        raise HTTPException(status_code=404, detail=f"no rollout with id {rollout_id!r}")


@app.post("/rollouts/{rollout_id}/tick", response_model=TickResult)
def tick_rollout(rollout_id: str) -> TickResult:
    rollout = _get_or_404(rollout_id)
    if rollout.engine.status in _SETTLED:
        raise HTTPException(status_code=409, detail=f"rollout already settled as {rollout.engine.status.value}")
    return _advance_one_tick(rollout)


@app.post("/rollouts/{rollout_id}/run", response_model=RunResult)
def run_rollout(rollout_id: str, max_ticks: int = 100) -> RunResult:
    rollout = _get_or_404(rollout_id)
    if rollout.engine.status in _SETTLED:
        raise HTTPException(status_code=409, detail=f"rollout already settled as {rollout.engine.status.value}")

    log: List[TickResult] = []
    ticks_run = 0
    while rollout.engine.status not in _SETTLED and ticks_run < max_ticks:
        log.append(_advance_one_tick(rollout))
        ticks_run += 1

    return RunResult(
        settled=rollout.engine.status in _SETTLED,
        final_status=rollout.engine.status.value,
        ticks_run=ticks_run,
        log=log,
    )
