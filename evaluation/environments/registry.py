"""Resolve a platform to a Harbor environment implementation."""

ENVIRONMENTS = {
    "local": "evaluation.environments.docker:HarnessDockerEnvironment",
    "daytona": "evaluation.environments.daytona:HarnessDaytonaEnvironment",
    "e2b": "evaluation.environments.e2b:HarnessE2BEnvironment",
}


def environment_config(provider: dict, benchmark: str) -> dict:
    kwargs = dict(provider.get("kwargs", {}))
    if "benchmark" in kwargs:
        raise ValueError("Provider kwargs cannot change the frozen task source")
    return {
        "import_path": provider.get("import_path") or ENVIRONMENTS[provider["type"]],
        "delete": True,
        "kwargs": {**kwargs, "benchmark": benchmark},
    }
