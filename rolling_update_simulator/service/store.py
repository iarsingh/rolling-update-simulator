"""In-memory registry of active rollouts, keyed by id.

This is the piece that turns the original single-rollout simulator into
something that can host many concurrent rollouts: each `Rollout` owns its
own `RolloutEngine` + `Cluster` pair, exactly as `simulator.run()` did, just
addressable by id instead of held in local variables.

A real deployment would back this with a database so rollouts survive a
process restart; the lock-guarded dict is the smallest thing that is safe
under FastAPI's threaded request handling for a reference implementation.
"""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..cluster import Cluster
from ..engine import RolloutEngine


@dataclass
class Rollout:
    id: str
    engine: RolloutEngine
    cluster: Cluster
    tick: int = 0


class RolloutStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rollouts: Dict[str, Rollout] = {}
        self._ids = itertools.count(1)

    def create(self, engine: RolloutEngine, cluster: Cluster) -> Rollout:
        with self._lock:
            rollout_id = f"ro-{next(self._ids)}"
            rollout = Rollout(id=rollout_id, engine=engine, cluster=cluster)
            self._rollouts[rollout_id] = rollout
            return rollout

    def get(self, rollout_id: str) -> Optional[Rollout]:
        with self._lock:
            return self._rollouts.get(rollout_id)

    def list(self) -> List[Rollout]:
        with self._lock:
            return list(self._rollouts.values())

    def delete(self, rollout_id: str) -> bool:
        with self._lock:
            return self._rollouts.pop(rollout_id, None) is not None


# Process-wide singleton. Each uvicorn worker process gets its own store,
# which is why the service is meant to run as a single worker (see README) --
# scaling to many workers/replicas requires swapping this for shared storage.
store = RolloutStore()
