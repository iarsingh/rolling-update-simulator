"""Load test for the rollout-demo Deployment on minikube.

Point Locust's host at the Service tunnel URL (see service-url.txt), start
it with the web UI, and click "Start swarming". Watch requests/sec, response
times, and the failure count stay stable while you trigger a rolling update
with `kubectl set image` in another terminal -- that's rule 2 (availability)
holding under real traffic, not just simulated ticks.

Each nginx image tag reports its own version in the `Server` response
header (e.g. "nginx/1.25.5" for the v1 image, "nginx/1.27.5" for v2), so
every request is also logged under a synthetic "backend" entry named for
whichever version actually answered. Watch the Locust stats table during a
rollout: the v1 row's request rate falls to zero while the v2 row's climbs
-- that's the live traffic mix shifting as pods are replaced, with the
"Total" row's failure count staying at zero throughout if rule 2 holds.
"""

from locust import HttpUser, task, constant_pacing

VERSION_TAGS = {
    "1.25": "v1 (nginx 1.25)",
    "1.27": "v2 (nginx 1.27)",
}


def label_for(server_header: str) -> str:
    for tag, label in VERSION_TAGS.items():
        if tag in server_header:
            return label
    return "unknown version"


class RolloutTrafficUser(HttpUser):
    wait_time = constant_pacing(0.2)  # ~5 requests/sec per simulated user

    @task
    def hit_root(self):
        with self.client.get("/", catch_response=True) as resp:
            version = label_for(resp.headers.get("Server", ""))
            # Extra row in the stats table, broken out by which backend
            # version actually served the request -- in addition to the
            # normal "/" row Locust logs automatically.
            self.environment.stats.log_request(
                "backend", version, resp.elapsed.total_seconds() * 1000, len(resp.content)
            )
            resp.success()
