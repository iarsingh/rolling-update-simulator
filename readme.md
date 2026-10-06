# Rolling Update Simulator

<!-- project-guide:start -->
## Project guide

[Project architecture](PROJECT_ARCHITECTURE.md) · [Interview questions and answers](INTERVIEW_QA.md)

Use the architecture document for the component diagram, implementation boundaries, and verification entry points. The interview guide includes source-backed answers and project walkthroughs.

### Implementation map

| Component | Responsibility |
| --- | --- |
| [`rolling_update_simulator/service/app.py`](rolling_update_simulator/service/app.py) | HTTP handlers: `POST /rollouts`, `GET /rollouts`, `GET /rollouts/{rollout_id}`, `DELETE /rollouts/{rollout_id}`, `POST /rollouts/{rollout_id}/tick` |
| [`rolling_update_simulator/cluster.py`](rolling_update_simulator/cluster.py) | Functions: `always_healthy`, `apply`, `tick`, `active_count`, `ready_count`, `_find` |
| [`rolling_update_simulator/engine.py`](rolling_update_simulator/engine.py) | Functions: `__post_init__`, `min_available`, `max_active`, `__init__`, `config`, `record_failure`, `plan` |
| [`rolling_update_simulator/simulator.py`](rolling_update_simulator/simulator.py) | Functions: `run`, `_report`, `_seed`, `_demo_healthy_rollout`, `_demo_failing_new_version` |
| [`k8s-sanity-check/locustfile.py`](k8s-sanity-check/locustfile.py) | Functions: `label_for`, `hit_root` |
| [`rollout-architecture.html`](rollout-architecture.html) | Implementation or supporting configuration |
| [`rollout-simulator.html`](rollout-simulator.html) | Implementation or supporting configuration |
| [`requirements.txt`](requirements.txt) | Implementation or supporting configuration |
| [`k8s-sanity-check/loadtest-with-rollout.sh`](k8s-sanity-check/loadtest-with-rollout.sh) | Implementation or supporting configuration |
| [`k8s-sanity-check/loadtest.sh`](k8s-sanity-check/loadtest.sh) | Implementation or supporting configuration |
| [`rolling_update_simulator/__init__.py`](rolling_update_simulator/__init__.py) | Implementation or supporting configuration |
| [`rolling_update_simulator/models.py`](rolling_update_simulator/models.py) | Functions: `is_active`, `is_ready`, `__str__` |
| [`tests/__init__.py`](tests/__init__.py) | Executable checks and regression examples |
| [`tests/test_engine.py`](tests/test_engine.py) | Executable checks and regression examples |
| [`readme.md`](readme.md) | Project explanations or operating notes |
| [`rolling_update_simulator/service/README.md`](rolling_update_simulator/service/README.md) | Project explanations or operating notes |

### Local setup and verification

From the repository root (the commands follow the checked-in manifests):

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

<!-- project-guide:end -->

<!-- repository-summary -->
A Python simulator and interactive showcase for safe rolling deployments under capacity, availability, and resource constraints.
<!-- /repository-summary -->

Coding Exercise – Rolling Update Simulator
Implement a simulator for performing a rolling update of an application.

An application is currently running multiple instances of version v1. The deployment needs to
be updated to v2 while ensuring that the application remains available throughout the rollout.
Your task is to implement the rollout algorithm. You can assume and state the desired input
parameters. Implement a rollout engine that repeatedly determines the next actions required
to move the deployment from the current state to the desired state.
Rollout Rules
Your implementation must satisfy all of the following constraints.
1. The system should not consume more than the available resources at any point of time.
2. The system should be available for the entire duration with at least the defined capacity.
3. System should support a valid rollout if it cannot reach the desired state.
4. Ensure that your solution is clean, follows standard best practices and is readable and
easy to maintain.

## Implementation

A dependency-free Python implementation lives in [rolling_update_simulator/](rolling_update_simulator/).

### Design

- **`RolloutEngine`** (`engine.py`) is a pure decision function: given the current fleet of
  instances it returns the CREATE/TERMINATE actions to take *this tick*. It holds no
  infrastructure logic, so it can drive either the in-memory simulation below or, in principle,
  a real scheduler/reconciliation loop.
- **`Cluster`** (`cluster.py`) simulates instance lifecycles (starting → ready/failed,
  terminating → terminated) deterministically, with a pluggable health check so tests can inject
  failures.
- **`simulator.py`** drives the engine + cluster tick by tick and prints progress; run it with
  `python3 -m rolling_update_simulator.simulator` for a demo of both a healthy rollout and one
  that can't reach the desired state.

### Input parameters (assumed)

| Parameter | Meaning |
|---|---|
| `desired_replicas` | Steady-state number of instances that should be serving traffic. |
| `max_surge` | Extra instances allowed beyond `desired_replicas` while rolling out. |
| `max_unavailable` | Instances allowed to be not-ready at once; the engine guarantees at least `desired_replicas - max_unavailable` ready instances at every tick. |
| `resource_capacity` | Hard infrastructure ceiling on concurrently active instances, independent of `max_surge`. |
| `max_new_version_failures` | Health-check failures tolerated before the engine gives up on the new version and rolls back. |

### How each rule is satisfied

1. **Never exceed available resources** — every CREATE is bounded by
   `min(max_surge headroom, resource_capacity headroom)` before it's issued (`engine.py:_plan_creates`).
2. **Stay available at ≥ defined capacity** — a READY instance is only terminated if the fleet
   has *spare* ready capacity above `min_available`; termination is never based on an
   optimistic guess that a replacement will succeed (`engine.py:_plan_terminates`).
3. **Support a valid rollout if the desired state is unreachable** — if new-version instances
   keep failing health checks past `max_new_version_failures`, the engine switches its target
   back to the old version and drives the fleet there using the exact same
   capacity/availability-safe logic, so the rollback is itself a valid rollout rather than a
   special-cased escape hatch. Additionally, `RolloutConfig` rejects configurations that are
   mathematically impossible to roll out safely (e.g. `max_surge == 0 and max_unavailable == 0`).
4. **Clean/maintainable** — planning, lifecycle simulation, and orchestration are separated into
   independently testable modules; see [tests/test_engine.py](tests/test_engine.py).

### Running

```bash
python3 -m unittest tests.test_engine -v      # unit tests (stdlib, no deps)
python3 -m rolling_update_simulator.simulator # demo: healthy rollout + automatic rollback
```

### Real-cluster sanity check

As a sanity check (not a substitute for the tests above, since it exercises Kubernetes' own
Deployment controller rather than this code), [k8s-sanity-check/deployment.yaml](k8s-sanity-check/deployment.yaml)
was applied to a local minikube cluster with the same `desired_replicas=4, max_surge=1,
max_unavailable=1` used in the simulator's demo, then rolled from `nginx:1.25-alpine` to
`nginx:1.27-alpine`. Observed pod counts matched the simulator's invariants throughout: total
pods peaked at 5 (`desired + max_surge`) and ready pods never dropped below 3
(`desired - max_unavailable`).

## Documentation checks

Project architecture, interview guides, and local source links are checked automatically on pushes and pull requests. Run the same check locally:

```bash
python3 .github/scripts/validate_project_docs.py
```
