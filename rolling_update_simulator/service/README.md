# Rolling Update Simulator — HTTP microservice

Wraps `RolloutEngine` + `Cluster` in a FastAPI app so multiple rollouts can be
created and advanced over HTTP instead of driven by a local Python loop.
Each rollout keeps its own engine + cluster, keyed by id, in an in-memory
store (`store.py`) — see the design doc's Low-Level Design section for the
full request/response contract and its trade-offs.

## Run

```bash
pip install -r requirements.txt
uvicorn rolling_update_simulator.service.app:app --reload
```

Interactive API docs are then at `http://127.0.0.1:8000/docs`.

## Endpoints

| Method & path                    | Purpose                                            |
|-----------------------------------|-----------------------------------------------------|
| `POST /rollouts`                  | Create a rollout (config + seeded old-version fleet) |
| `GET /rollouts`                   | List all rollouts and their current status           |
| `GET /rollouts/{id}`              | Full detail: status, tick count, fleet snapshot       |
| `POST /rollouts/{id}/tick`        | Advance exactly one tick                              |
| `POST /rollouts/{id}/run`         | Advance until settled or `max_ticks` is hit           |
| `DELETE /rollouts/{id}`           | Drop a rollout from the store                         |

## Example

```bash
curl -s localhost:8000/rollouts -X POST -H 'content-type: application/json' -d '{
  "old_version": "v1", "new_version": "v2",
  "config": {"desired_replicas": 4, "max_surge": 1, "max_unavailable": 1, "resource_capacity": 6}
}' | python3 -m json.tool

curl -s localhost:8000/rollouts/ro-1/run -X POST | python3 -m json.tool
```

## Notes

- `health_check_mode: "fail_new_version"` reproduces `simulator.py`'s
  automatic-rollback demo over the API (every new-version instance fails
  its check, so the rollout gives up and reverses direction).
- The store is process-local, in-memory state — run a single worker
  (`uvicorn ... ` without `--workers`) or rollouts created on one worker
  won't be visible on another. See the design doc's Limitations table for
  what swapping in shared storage would take.
