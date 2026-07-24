"""The rollout planning algorithm.

`RolloutEngine` is a pure decision-maker: given the current fleet of
instances, it returns the list of CREATE/TERMINATE actions to take *this
tick*. It holds no infrastructure logic itself (that's `Cluster`'s job) and
runs the same way whether driven by a simulation loop or a real
scheduler/reconciliation loop.
"""

from __future__ import annotations  # forward references in type hints below

from dataclasses import dataclass  # RolloutConfig is a plain immutable value object
from typing import List, Optional  # List[...] / Optional[...] type hints

from .models import Action, ActionType, Instance, InstanceState, RolloutStatus  # shared types


@dataclass(frozen=True)  # frozen: config can't be mutated after construction, safe to share
class RolloutConfig:
    """Parameters that fully describe a rollout.

    desired_replicas:
        Steady-state number of instances that should be serving traffic.
    max_surge:
        Extra instances allowed beyond desired_replicas while rolling out
        (i.e. how far the fleet may grow to make room for new instances
        before old ones are removed).
    max_unavailable:
        Instances allowed to be not-ready at any point in time. The engine
        guarantees at least `min_available` ready instances at every tick.
    resource_capacity:
        Hard infrastructure ceiling on concurrently active instances
        (starting + ready + terminating), independent of max_surge. Pass
        None for "no separate infra limit" (max_surge alone governs).
    max_new_version_failures:
        Number of new-version health-check failures tolerated before the
        engine concludes the desired state is unreachable and rolls back
        to the old version instead.
    """

    desired_replicas: int                        # target number of serving instances
    max_surge: int = 1                            # extra instances allowed above desired_replicas
    max_unavailable: int = 0                      # instances allowed to be not-ready at once
    resource_capacity: Optional[int] = None       # hard infra ceiling, or None if unbounded
    max_new_version_failures: int = 3             # failures tolerated before triggering rollback

    def __post_init__(self) -> None:
        # Validated eagerly so an impossible rollout is rejected at config
        # time rather than silently stalling once the engine starts running.
        if self.desired_replicas <= 0:
            raise ValueError("desired_replicas must be positive")
        if self.max_surge < 0 or self.max_unavailable < 0:
            raise ValueError("max_surge and max_unavailable must be non-negative")
        if self.max_surge == 0 and self.max_unavailable == 0:
            # With no surge room and no tolerated unavailability, a new
            # instance can never be created without first freeing a slot,
            # and no old instance can ever be freed without breaching the
            # availability floor -- the rollout is mathematically stuck.
            raise ValueError(
                "max_surge and max_unavailable cannot both be 0: there would be no "
                "room to introduce a new-version instance without breaching availability"
            )
        if self.resource_capacity is not None and self.resource_capacity < self.desired_replicas:
            raise ValueError("resource_capacity must be at least desired_replicas")

    @property
    def min_available(self) -> int:
        # The floor: how many ready instances must exist at every tick.
        return max(self.desired_replicas - self.max_unavailable, 0)

    @property
    def max_active(self) -> int:
        # The surge-based ceiling: how many active instances may exist at once.
        return self.desired_replicas + self.max_surge


class RolloutEngine:
    """Decides, tick by tick, how to move a fleet from `old_version` to
    `new_version` without ever exceeding `resource_capacity`/`max_surge`
    (rule 1) or dropping below `min_available` ready instances (rule 2).

    If the new version keeps failing health checks, the engine gives up on
    reaching the desired state and drives the fleet back to `old_version`
    instead (rule 3) -- using the exact same capacity/availability-safe
    logic, so the rollback is itself a valid rollout.
    """

    def __init__(self, config: RolloutConfig, old_version: str, new_version: str):
        self._config = config                       # immutable rollout parameters
        self.old_version = old_version               # version being rolled away from
        self.new_version = new_version               # version being rolled toward
        self.status = RolloutStatus.IN_PROGRESS      # starts by advancing toward new_version
        self._new_version_failures = 0               # running count of new-version health failures

    @property
    def config(self) -> RolloutConfig:
        return self._config  # read-only view for callers/tests

    def record_failure(self, instance: Instance) -> None:
        """Notify the engine that `instance` transitioned to FAILED. Once
        failures exceed the configured tolerance, the engine switches to
        rolling back."""
        if instance.version != self.new_version or self.status is not RolloutStatus.IN_PROGRESS:
            return  # only new-version failures matter, and only while still advancing forward
        self._new_version_failures += 1
        if self._new_version_failures > self._config.max_new_version_failures:
            self.status = RolloutStatus.ROLLING_BACK  # tolerance exceeded: reverse direction

    def plan(self, instances: List[Instance]) -> List[Action]:
        """Return the actions to take this tick, given the current fleet."""
        if self.status in (RolloutStatus.COMPLETE, RolloutStatus.ROLLED_BACK):
            return []  # nothing left to do once settled

        rolling_back = self.status is RolloutStatus.ROLLING_BACK
        # Forward: grow new_version, shrink old_version. Rollback: the mirror image.
        target_version = self.old_version if rolling_back else self.new_version
        replacement_version = self.new_version if rolling_back else self.old_version

        creates = self._plan_creates(instances, target_version)
        # Project the creates so the terminate step never reasons about
        # stale ready/active counts within the same tick.
        projected = instances + [Instance(version=target_version) for _ in creates]
        terminates = self._plan_terminates(projected, replacement_version)

        if self._is_settled(projected, target_version):
            self.status = RolloutStatus.ROLLED_BACK if rolling_back else RolloutStatus.COMPLETE

        return creates + terminates  # order doesn't matter; Cluster applies both this tick

    def _plan_creates(self, instances: List[Instance], target_version: str) -> List[Action]:
        cfg = self._config
        total_active = sum(i.is_active() for i in instances)                              # rule 1 input: current load
        target_active = sum(i.is_active() and i.version == target_version for i in instances)  # already-in-flight target instances

        headroom = cfg.max_active - total_active               # room left under the surge ceiling
        if cfg.resource_capacity is not None:
            headroom = min(headroom, cfg.resource_capacity - total_active)  # also respect the infra ceiling

        still_needed = cfg.desired_replicas - target_active    # how many more target-version instances are required
        to_create = max(min(headroom, still_needed), 0)        # never negative, never more than headroom allows

        return [Action(ActionType.CREATE, version=target_version) for _ in range(to_create)]

    def _plan_terminates(self, instances: List[Instance], replacement_version: str) -> List[Action]:
        cfg = self._config
        ready_count = sum(i.is_ready() for i in instances)     # rule 2 input: currently-serving instances
        removable = [
            i for i in instances
            if i.version == replacement_version and i.state is InstanceState.READY
        ]  # only ready replacement-version instances are safe termination candidates

        # Only give up ready capacity we don't need to stay above the floor.
        spare_ready = ready_count - cfg.min_available           # how many ready instances are "spare"
        to_remove = max(min(spare_ready, len(removable)), 0)    # never negative, never more than exist

        return [Action(ActionType.TERMINATE, instance_id=i.id) for i in removable[:to_remove]]

    def _is_settled(self, instances: List[Instance], target_version: str) -> bool:
        replacement_remains = any(
            i.version != target_version and i.state != InstanceState.TERMINATED for i in instances
        )  # any non-target-version instance still around (even winding down) means not settled
        target_ready = sum(i.is_ready() and i.version == target_version for i in instances)  # fully-serving target instances
        return not replacement_remains and target_ready >= self._config.desired_replicas
