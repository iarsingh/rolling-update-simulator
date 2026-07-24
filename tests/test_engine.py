import unittest

from rolling_update_simulator.cluster import Cluster
from rolling_update_simulator.engine import RolloutConfig, RolloutEngine
from rolling_update_simulator.models import Instance, InstanceState, RolloutStatus


def seed(cluster: Cluster, version: str, count: int) -> None:
    for _ in range(count):
        cluster.instances.append(Instance(version=version, state=InstanceState.READY))


def run_and_check_invariants(test: unittest.TestCase, engine: RolloutEngine, cluster: Cluster, max_ticks: int = 100):
    """Drives the engine/cluster loop while asserting rules 1 and 2 hold
    after every single action and every single tick."""
    settled = (RolloutStatus.COMPLETE, RolloutStatus.ROLLED_BACK)
    tick = 0
    while engine.status not in settled and tick < max_ticks:
        actions = engine.plan(cluster.instances)
        cluster.apply(actions)

        test.assertLessEqual(cluster.active_count(), engine.config.max_active)
        if engine.config.resource_capacity is not None:
            test.assertLessEqual(cluster.active_count(), engine.config.resource_capacity)

        for instance in cluster.tick():
            engine.record_failure(instance)

        test.assertGreaterEqual(cluster.ready_count(), engine.config.min_available)
        tick += 1

    test.assertLess(tick, max_ticks, "rollout did not settle in time")
    return engine.status


class HealthyRolloutTests(unittest.TestCase):
    def test_reaches_desired_state(self):
        config = RolloutConfig(desired_replicas=4, max_surge=1, max_unavailable=1, resource_capacity=6)
        engine = RolloutEngine(config, old_version="v1", new_version="v2")
        cluster = Cluster()
        seed(cluster, "v1", 4)

        status = run_and_check_invariants(self, engine, cluster)

        self.assertEqual(status, RolloutStatus.COMPLETE)
        self.assertEqual(len(cluster.instances), 4)
        self.assertTrue(all(i.version == "v2" and i.is_ready() for i in cluster.instances))

    def test_tight_capacity_still_progresses(self):
        # Only one instance of headroom above desired_replicas: surge and
        # unavailability trade off against the same slack, exercising the
        # resource_capacity ceiling as the binding constraint rather than
        # max_surge.
        config = RolloutConfig(desired_replicas=5, max_surge=3, max_unavailable=2, resource_capacity=6)
        engine = RolloutEngine(config, old_version="v1", new_version="v2")
        cluster = Cluster()
        seed(cluster, "v1", 5)

        status = run_and_check_invariants(self, engine, cluster)

        self.assertEqual(status, RolloutStatus.COMPLETE)
        self.assertEqual(len(cluster.instances), 5)

    def test_scales_up_when_starting_below_desired_replicas(self):
        config = RolloutConfig(desired_replicas=6, max_surge=2, max_unavailable=1, resource_capacity=8)
        engine = RolloutEngine(config, old_version="v1", new_version="v2")
        cluster = Cluster()
        seed(cluster, "v1", 3)  # under-provisioned starting point

        status = run_and_check_invariants(self, engine, cluster)

        self.assertEqual(status, RolloutStatus.COMPLETE)
        self.assertEqual(len(cluster.instances), 6)


class UnreachableDesiredStateTests(unittest.TestCase):
    def test_always_failing_new_version_rolls_back(self):
        config = RolloutConfig(
            desired_replicas=4, max_surge=1, max_unavailable=1,
            resource_capacity=6, max_new_version_failures=2,
        )
        engine = RolloutEngine(config, old_version="v1", new_version="v2")
        cluster = Cluster(health_check=lambda i: i.version != "v2")
        seed(cluster, "v1", 4)

        status = run_and_check_invariants(self, engine, cluster)

        self.assertEqual(status, RolloutStatus.ROLLED_BACK)
        self.assertEqual(len(cluster.instances), 4)
        self.assertTrue(all(i.version == "v1" and i.is_ready() for i in cluster.instances))

    def test_intermittently_failing_new_version_eventually_completes(self):
        # Fails a bounded number of times, then starts succeeding -- the
        # failure counter must not be so trigger-happy that a recoverable
        # rollout gets rolled back unnecessarily.
        attempts = {"count": 0}

        def flaky_health_check(instance: Instance) -> bool:
            if instance.version != "v2":
                return True
            attempts["count"] += 1
            return attempts["count"] > 3

        config = RolloutConfig(
            desired_replicas=4, max_surge=1, max_unavailable=1,
            resource_capacity=6, max_new_version_failures=5,
        )
        engine = RolloutEngine(config, old_version="v1", new_version="v2")
        cluster = Cluster(health_check=flaky_health_check)
        seed(cluster, "v1", 4)

        status = run_and_check_invariants(self, engine, cluster)

        self.assertEqual(status, RolloutStatus.COMPLETE)


class ConfigValidationTests(unittest.TestCase):
    def test_rejects_zero_surge_and_zero_unavailable(self):
        with self.assertRaises(ValueError):
            RolloutConfig(desired_replicas=3, max_surge=0, max_unavailable=0)

    def test_rejects_capacity_below_desired_replicas(self):
        with self.assertRaises(ValueError):
            RolloutConfig(desired_replicas=5, resource_capacity=4)

    def test_rejects_non_positive_desired_replicas(self):
        with self.assertRaises(ValueError):
            RolloutConfig(desired_replicas=0)


if __name__ == "__main__":
    unittest.main()
