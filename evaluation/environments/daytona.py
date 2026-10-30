"""Daytona execution using Harbor's native task/Compose lifecycle."""

from harbor.environments.daytona import DaytonaEnvironment

from .base import TaskEnvironmentMixin


class HarnessDaytonaEnvironment(TaskEnvironmentMixin, DaytonaEnvironment):
    pass
