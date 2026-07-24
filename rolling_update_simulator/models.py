"""Core data types shared by the engine, cluster simulation, and driver."""

from __future__ import annotations  # lets type hints reference classes defined later in the file

from dataclasses import dataclass, field  # dataclass: boilerplate-free value classes; field: for factory defaults
from enum import Enum  # closed sets of named constants (states/statuses/action types)
from itertools import count  # infinite counter used to hand out unique instance ids
from typing import Optional  # marks fields that may be None


class InstanceState(str, Enum):  # str+Enum so values serialize/print as plain strings
    STARTING = "starting"        # just created, health check not yet run
    READY = "ready"               # health check passed, serving traffic
    TERMINATING = "terminating"   # shutting down, still occupies resources
    TERMINATED = "terminated"     # fully removed, no longer tracked
    FAILED = "failed"             # health check failed, no longer tracked


class RolloutStatus(str, Enum):       # overall state of a rollout, owned by RolloutEngine
    IN_PROGRESS = "in_progress"       # moving fleet from old_version to new_version
    ROLLING_BACK = "rolling_back"     # new version unhealthy; moving fleet back to old_version
    COMPLETE = "complete"             # fleet fully on new_version
    ROLLED_BACK = "rolled_back"       # fleet fully back on old_version after a failed rollout


class ActionType(str, Enum):   # the only two verbs the engine can issue
    CREATE = "create"          # bring up a new instance of a given version
    TERMINATE = "terminate"    # start shutting down a specific instance


_id_counter = count(1)  # module-level counter; every Instance gets the next sequential id


@dataclass
class Instance:                                                   # a single running (or starting/stopping) unit
    version: str                                                  # e.g. "v1" or "v2"
    state: InstanceState = InstanceState.STARTING                 # lifecycle stage, defaults to just-created
    id: int = field(default_factory=lambda: next(_id_counter))    # unique id assigned at construction time
    ticks_in_state: int = 0                                       # how many ticks it has spent in `state`

    def is_active(self) -> bool:
        """Whether this instance currently occupies resource capacity."""
        # STARTING/READY/TERMINATING all still hold a slot on the infra; TERMINATED/FAILED do not
        return self.state in (InstanceState.STARTING, InstanceState.READY, InstanceState.TERMINATING)

    def is_ready(self) -> bool:
        return self.state is InstanceState.READY  # only READY instances count toward serving capacity


@dataclass(frozen=True)  # actions are immutable value objects returned by the engine each tick
class Action:
    type: ActionType                        # CREATE or TERMINATE
    version: Optional[str] = None           # set for CREATE: which version to bring up
    instance_id: Optional[int] = None       # set for TERMINATE: which instance to tear down

    def __str__(self) -> str:
        if self.type is ActionType.CREATE:
            return f"CREATE(version={self.version})"
        return f"TERMINATE(id={self.instance_id})"
