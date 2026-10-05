# rolling-update-simulator — interview questions and answers

[README](readme.md) · [Project architecture](PROJECT_ARCHITECTURE.md)

Answers below use this repository’s files and implementation. They distinguish existing behavior from suggested extensions; source links let you verify each walkthrough.

## 1. What problem does rolling-update-simulator address, and what can you demonstrate?

A Python simulator and interactive showcase for safe rolling deployments under capacity, availability, and resource constraints.

I would demonstrate the linked implementation or examples and distinguish that evidence from any planned production features. Start with [`readme.md`](readme.md).

## 2. How is this repository organized?

- [`rolling_update_simulator/service/app.py`](rolling_update_simulator/service/app.py): Implementation or supporting configuration.
- [`rolling_update_simulator/cluster.py`](rolling_update_simulator/cluster.py): Implementation or supporting configuration.
- [`rolling_update_simulator/engine.py`](rolling_update_simulator/engine.py): Implementation or supporting configuration.
- [`rolling_update_simulator/simulator.py`](rolling_update_simulator/simulator.py): Implementation or supporting configuration.
- [`k8s-sanity-check/locustfile.py`](k8s-sanity-check/locustfile.py): Implementation or supporting configuration.
- [`rollout-architecture.html`](rollout-architecture.html): Implementation or supporting configuration.
- [`rollout-simulator.html`](rollout-simulator.html): Implementation or supporting configuration.
- [`requirements.txt`](requirements.txt): Implementation or supporting configuration.

[PROJECT_ARCHITECTURE.md](PROJECT_ARCHITECTURE.md) contains the component diagram and the implementation walkthrough.

## 3. Can you walk through `tick` and explain the decision it makes?

The main walkthrough here is `tick(self)` in [`rolling_update_simulator/cluster.py`](rolling_update_simulator/cluster.py#L41). Advance every instance by one tick. Returns instances that
transitioned to FAILED this tick, for the engine to record.

```python
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
```

This is an excerpt; follow the source link for the rest of the branches.

The implementation calls `newly_failed.append`, `self.health_check`. In an interview, trace those calls in execution order using a fixture input.

## 4. What responsibility does `plan` have?

`plan(self, instances: List[Instance])` is defined in [`rolling_update_simulator/engine.py`](rolling_update_simulator/engine.py#L109). Return the actions to take this tick, given the current fleet.

Its return expressions include:

- `creates + terminates`
- `[]`

It uses `Instance`, `self._is_settled`, `self._plan_creates`, `self._plan_terminates`. This is the code path I would compare against the caller to explain responsibility boundaries.

## 5. What input validation and failure behavior are implemented?

Explicit failure paths include:

- `ValueError('desired_replicas must be positive')` in [`rolling_update_simulator/engine.py`](rolling_update_simulator/engine.py#L51).
- `ValueError('max_surge and max_unavailable must be non-negative')` in [`rolling_update_simulator/engine.py`](rolling_update_simulator/engine.py#L53).
- `ValueError('max_surge and max_unavailable cannot both be 0: there would be no room to introduce a new-version instance without breaching availability')` in [`rolling_update_simulator/engine.py`](rolling_update_simulator/engine.py#L59).
- `ValueError('resource_capacity must be at least desired_replicas')` in [`rolling_update_simulator/engine.py`](rolling_update_simulator/engine.py#L64).
- `RuntimeError(f'rollout did not settle within {max_ticks} ticks')` in [`rolling_update_simulator/simulator.py`](rolling_update_simulator/simulator.py#L31).
- `HTTPException(status_code=404, detail=f'no rollout with id {rollout_id!r}')` in [`rolling_update_simulator/service/app.py`](rolling_update_simulator/service/app.py#L70).
- `HTTPException(status_code=404, detail=f'no rollout with id {rollout_id!r}')` in [`rolling_update_simulator/service/app.py`](rolling_update_simulator/service/app.py#L145).

I would test both the condition that reaches each exception and the caller that translates it. An explicit raise does not mean every malformed input or dependency failure is handled.

## 6. Which test would you use to demonstrate correctness?

[`tests/test_engine.py`](tests/test_engine.py#L37) contains `test_reaches_desired_state`:

```python
    def test_reaches_desired_state(self):
        config = RolloutConfig(desired_replicas=4, max_surge=1, max_unavailable=1, resource_capacity=6)
        engine = RolloutEngine(config, old_version="v1", new_version="v2")
        cluster = Cluster()
        seed(cluster, "v1", 4)

        status = run_and_check_invariants(self, engine, cluster)

        self.assertEqual(status, RolloutStatus.COMPLETE)
        self.assertEqual(len(cluster.instances), 4)
        self.assertTrue(all(i.version == "v2" and i.is_ready() for i in cluster.instances))
```

This is a concrete regression example from the repository. Its assertions establish that case; they do not establish behavior for every input or under production load.

## 7. What HTTP interface does the code expose?

- `POST /rollouts` → `create_rollout` in [`rolling_update_simulator/service/app.py`](rolling_update_simulator/service/app.py#L96).
- `GET /rollouts` → `list_rollouts` in [`rolling_update_simulator/service/app.py`](rolling_update_simulator/service/app.py#L124).
- `GET /rollouts/{rollout_id}` → `get_rollout` in [`rolling_update_simulator/service/app.py`](rolling_update_simulator/service/app.py#L129).
- `DELETE /rollouts/{rollout_id}` → `delete_rollout` in [`rolling_update_simulator/service/app.py`](rolling_update_simulator/service/app.py#L143).
- `POST /rollouts/{rollout_id}/tick` → `tick_rollout` in [`rolling_update_simulator/service/app.py`](rolling_update_simulator/service/app.py#L149).
- `POST /rollouts/{rollout_id}/run` → `run_rollout` in [`rolling_update_simulator/service/app.py`](rolling_update_simulator/service/app.py#L157).

These are literal decorators. Application/router prefixes, authentication, and middleware must be checked in the corresponding setup code.

## 8. Where does state live, and what happens with multiple workers?

Module-level containers include `VERSION_TAGS` in [`k8s-sanity-check/locustfile.py`](k8s-sanity-check/locustfile.py); `__all__` in [`rolling_update_simulator/__init__.py`](rolling_update_simulator/__init__.py).

These containers belong to a Python process. Inspect which are constant fixtures and which are mutated. Mutable process state needs an explicit shared-storage or synchronization strategy before multiple workers can provide consistent behavior.

## 9. How would another engineer reproduce your walkthrough?

Start from the repository root:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

These commands follow repository manifests; environment setup and command results still need to be checked on the target machine.

## 10. How would you add CI without confusing it with deployment?

First automate the repository-specific checks above, including documentation link validation. Add deployment only after defining the target environment, required credentials, approval boundary, smoke test, and rollback procedure. No GitHub Actions workflow is asserted by the inspected inventory.

## 11. How would you present this project in a Forward Deployed Engineer interview?

Start with the user and operational problem described in [`readme.md`](readme.md). Explain one constraint that changes the implementation, show the linked code or example, and walk through a success case and a failure case. Agree on a measurable acceptance criterion before expanding the solution, and leave a handoff with data boundaries and rollback ownership. Any proposed production or business metric should be identified as a target until measured.

## 12. What is the input-to-output contract of `tick`?

In [`rolling_update_simulator/cluster.py`](rolling_update_simulator/cluster.py#L41), `tick(self)` receives the inputs. The function computes these intermediate values:

- `newly_failed = []`
- `self.instances = [i for i in self.instances if i.state not in (InstanceState.TERMINATED, InstanceState.FAILED)]`

Its result is defined by:

- `newly_failed`

## 13. Which decision rules or boundary conditions should an interviewer challenge?

The implementation in [`rolling_update_simulator/cluster.py`](rolling_update_simulator/cluster.py#L41) branches on:

- `instance.state is InstanceState.STARTING and instance.ticks_in_state >= self.startup_ticks`
- `self.health_check(instance)`
- `instance.state is InstanceState.TERMINATING and instance.ticks_in_state >= self.shutdown_ticks`

A useful extension is a table-driven test that covers each condition just below, at, and above its boundary where applicable. These expressions are the current rules; changing them changes behavior and should be justified by the project’s acceptance criteria.
