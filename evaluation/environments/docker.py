"""Local Docker execution using Harbor's native task/Compose lifecycle."""

from harbor.environments.docker.docker import DockerEnvironment

from .base import TaskEnvironmentMixin


class HarnessDockerEnvironment(TaskEnvironmentMixin, DockerEnvironment):
    pass
