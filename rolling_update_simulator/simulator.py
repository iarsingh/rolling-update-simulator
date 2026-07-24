"""Drives the engine + cluster tick by tick and reports progress.

Run directly for a demo of a healthy rollout and a rollout that can't reach
the desired state (new version fails health checks) and safely rolls back:

    python3 -m rolling_update_simulator.simulator
"""

from __future__ import annotations  # forward references in type hints below

from .cluster import Cluster                                   # infrastructure/lifecycle simulation
from .engine import RolloutConfig, RolloutEngine                # planning algorithm + its parameters
from .models import Instance, InstanceState, RolloutStatus      # shared types


def run(engine: RolloutEngine, cluster: Cluster, max_ticks: int = 100, verbose: bool = False) -> RolloutStatus:
    tick = 0                                                     # current tick counter, for the printed log and the safety cap
    settled = (RolloutStatus.COMPLETE, RolloutStatus.ROLLED_BACK)  # terminal states that end the loop
    while engine.status not in settled and tick < max_ticks:
        status_before = engine.status                            # captured before plan() can flip it mid-tick
        actions = engine.plan(cluster.instances)                 # ask the engine what to do this tick
        cluster.apply(actions)                                   # hand the actions to the simulated infra
        for instance in cluster.tick():                          # advance lifecycles; returns newly-FAILED instances
            engine.record_failure(instance)                      # let the engine track new-version health

        if verbose:
            _report(tick, status_before, actions, cluster, engine)
        tick += 1                                                 # move to the next tick

    if engine.status not in settled:
        raise RuntimeError(f"rollout did not settle within {max_ticks} ticks")  # defensive: should be unreachable for valid configs
    return engine.status


def _report(tick: int, status_before: RolloutStatus, actions, cluster: Cluster, engine: RolloutEngine) -> None:
    old = sum(i.version == engine.old_version for i in cluster.instances)   # old-version instance count, for the log line
    new = sum(i.version == engine.new_version for i in cluster.instances)   # new-version instance count, for the log line
    print(
        f"[tick {tick:02d}] status={status_before.value:<12} "
        f"active={cluster.active_count()} ready={cluster.ready_count()} "
        f"({engine.old_version}={old}, {engine.new_version}={new})  "
        f"actions={[str(a) for a in actions]}"
    )


def _seed(cluster: Cluster, version: str, count: int) -> None:
    for _ in range(count):
        cluster.instances.append(Instance(version=version, state=InstanceState.READY))  # start fully up and serving


def _demo_healthy_rollout() -> None:
    print("\n=== Demo 1: healthy rollout v1 -> v2 ===")
    config = RolloutConfig(desired_replicas=4, max_surge=1, max_unavailable=1, resource_capacity=6)  # 4 replicas, 1 surge, 1 unavailable, 6-instance ceiling
    engine = RolloutEngine(config, old_version="v1", new_version="v2")   # roll from v1 to v2
    cluster = Cluster(startup_ticks=1, shutdown_ticks=1)                 # default health check: always healthy
    _seed(cluster, "v1", config.desired_replicas)                        # start at steady state on v1

    status = run(engine, cluster, verbose=True)                          # drive the simulation, printing each tick
    print(f"Final status: {status.value}")


def _demo_failing_new_version() -> None:
    print("\n=== Demo 2: v2 is unhealthy -> automatic rollback ===")
    config = RolloutConfig(
        desired_replicas=4, max_surge=1, max_unavailable=1,
        resource_capacity=6, max_new_version_failures=2,   # tolerate only 2 failures before giving up on v2
    )
    engine = RolloutEngine(config, old_version="v1", new_version="v2")
    cluster = Cluster(
        startup_ticks=1,
        shutdown_ticks=1,
        health_check=lambda instance: instance.version != "v2",  # every v2 instance fails its health check
    )
    _seed(cluster, "v1", config.desired_replicas)

    status = run(engine, cluster, verbose=True)
    print(f"Final status: {status.value}")


if __name__ == "__main__":
    _demo_healthy_rollout()        # first scenario: rollout reaches the desired state
    _demo_failing_new_version()    # second scenario: rollout can't reach it, rolls back instead
