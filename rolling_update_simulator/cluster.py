"""A minimal, deterministic simulation of instance lifecycles.

`Cluster` plays the role of the underlying infrastructure: it applies the
actions the engine decides on and advances instance state over time
(starting -> ready/failed, terminating -> terminated). It knows nothing
about rollout policy -- that separation keeps the engine's decision logic
independently testable from the lifecycle timing/health simulation.
"""

from __future__ import annotations  # forward references in type hints below

from dataclasses import dataclass, field  # Cluster is a plain stateful value object
from typing import Callable, List  # HealthCheck type alias, list type hints

from .models import Action, ActionType, Instance, InstanceState  # shared types

HealthCheck = Callable[[Instance], bool]  # a function deciding READY vs FAILED for a just-started instance


def always_healthy(_instance: Instance) -> bool:
    return True  # default health check: every instance starts up successfully


@dataclass
class Cluster:
    startup_ticks: int = 1                              # ticks a STARTING instance takes before being health-checked
    shutdown_ticks: int = 1                              # ticks a TERMINATING instance takes before being removed
    health_check: HealthCheck = always_healthy           # pluggable, so tests/demos can inject failures
    instances: List[Instance] = field(default_factory=list)  # the live fleet

    def apply(self, actions: List[Action]) -> None:
        for action in actions:                                            # actions arrive from RolloutEngine.plan()
            if action.type is ActionType.CREATE:
                self.instances.append(Instance(version=action.version))   # spin up a new instance, starts STARTING
            else:
                instance = self._find(action.instance_id)                 # look up the instance to tear down
                if instance is not None and instance.state is not InstanceState.TERMINATING:
                    instance.state = InstanceState.TERMINATING            # begin graceful shutdown
                    instance.ticks_in_state = 0                           # reset the shutdown timer

    def tick(self) -> List[Instance]:
        """Advance every instance by one tick. Returns instances that
        transitioned to FAILED this tick, for the engine to record."""
        newly_failed = []                                    # collected for the caller to feed into record_failure
        for instance in self.instances:
            instance.ticks_in_state += 1                      # every instance ages by one tick, regardless of state
            if instance.state is InstanceState.STARTING and instance.ticks_in_state >= self.startup_ticks:
                if self.health_check(instance):                # startup window elapsed: run the health check once
                    instance.state = InstanceState.READY
                else:
                    instance.state = InstanceState.FAILED
                    newly_failed.append(instance)               # record so the engine can count it toward rollback
                instance.ticks_in_state = 0                     # reset timer for whichever state it entered
            elif instance.state is InstanceState.TERMINATING and instance.ticks_in_state >= self.shutdown_ticks:
                instance.state = InstanceState.TERMINATED       # shutdown window elapsed: fully gone next line

        # Infra reclaims failed/terminated instances; they no longer occupy capacity.
        self.instances = [
            i for i in self.instances
            if i.state not in (InstanceState.TERMINATED, InstanceState.FAILED)
        ]
        return newly_failed

    def active_count(self) -> int:
        return sum(i.is_active() for i in self.instances)   # rule 1 bookkeeping: current resource consumption

    def ready_count(self) -> int:
        return sum(i.is_ready() for i in self.instances)    # rule 2 bookkeeping: current serving capacity

    def _find(self, instance_id: int) -> Instance | None:
        return next((i for i in self.instances if i.id == instance_id), None)  # None if already removed
