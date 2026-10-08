import time
import unittest

from auto_designer.demand.agent_runtime import AgentTimeout, run_with_timeout
from auto_designer.usage import bind_time_accounting, provider_wait_scope


class TimeAccountingTest(unittest.TestCase):
    def test_provider_wait_does_not_consume_active_budget(self):
        with bind_time_accounting(enabled=True) as accounting:
            started = time.monotonic()
            with provider_wait_scope():
                time.sleep(0.12)
            self.assertGreaterEqual(accounting.snapshot()["provider_wait_ms"], 100)
            self.assertLess(accounting.active_seconds(), 0.05)
            self.assertGreaterEqual(time.monotonic() - started, 0.10)

    def test_active_work_still_times_out(self):
        with bind_time_accounting(enabled=True):
            with self.assertRaises(AgentTimeout) as raised:
                run_with_timeout(
                    lambda: time.sleep(0.15), 0.05, latency_isolated=True, wall_guard=1
                )
        self.assertEqual(raised.exception.timeout_class, "mechanism_timeout")

    def test_slow_provider_can_finish_inside_wall_guard(self):
        with bind_time_accounting(enabled=True):
            with provider_wait_scope():
                result = run_with_timeout(
                    lambda: (time.sleep(0.12), "ok")[1],
                    0.03,
                    latency_isolated=True,
                    wall_guard=1,
                )
        self.assertEqual(result, "ok")

    def test_timeout_invokes_cancellation_hook(self):
        cancelled = []
        with bind_time_accounting(enabled=True):
            with self.assertRaises(AgentTimeout):
                run_with_timeout(
                    lambda: time.sleep(0.15),
                    0.05,
                    latency_isolated=True,
                    wall_guard=1,
                    cancel=lambda: cancelled.append(True),
                )
        self.assertEqual(cancelled, [True])

    def test_resume_carries_elapsed_budget(self):
        with bind_time_accounting(
            enabled=True,
            restored={"wall_elapsed_ms": 900, "active_elapsed_ms": 900},
        ) as accounting:
            self.assertGreaterEqual(accounting.active_seconds(), 0.9)

    def test_wall_guard_during_provider_wait_is_infrastructure(self):
        with bind_time_accounting(enabled=True):
            with provider_wait_scope():
                with self.assertRaises(AgentTimeout) as raised:
                    run_with_timeout(
                        lambda: time.sleep(0.15),
                        0.01,
                        latency_isolated=True,
                        wall_guard=0.05,
                    )
        self.assertEqual(raised.exception.timeout_class, "infrastructure_timeout")


if __name__ == "__main__":
    unittest.main()
