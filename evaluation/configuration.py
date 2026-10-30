"""The single operator-editable configuration; generated manifests are records."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import yaml

HARNESS_NAMES = ("v0", "u8", "u8-direct", "u16", "u32", "claude-code", "meta-harness")


class ConfigurationError(ValueError):
    pass


def fields(value, allowed, label):
    if not isinstance(value, dict):
        raise ConfigurationError(f"{label} must be a mapping")
    extra = set(value) - set(allowed)
    if extra:
        raise ConfigurationError(f"Unknown {label} fields: {sorted(extra)}")
    return value


def positive(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigurationError(f"{label} must be a positive integer")
    return value


def boolean(value, label):
    if type(value) is not bool:
        raise ConfigurationError(f"{label} must be true or false")
    return value


def endpoint(value, label, optional=False):
    if optional and value is None:
        return None
    if (
        not isinstance(value, str)
        or urlparse(value).scheme not in {"http", "https"}
        or not urlparse(value).netloc
    ):
        raise ConfigurationError(f"{label} must be an HTTP(S) base URL")
    p = urlparse(value)
    if p.username or p.password or p.query or p.fragment:
        raise ConfigurationError(f"{label} cannot embed credentials, query parameters or fragments")
    return value.rstrip("/").removesuffix("/chat/completions")


def env_name(value, label):
    import re

    if not isinstance(value, str) or not re.fullmatch(r"[A-Z][A-Z0-9_]*", value):
        raise ConfigurationError(f"{label} must name an environment variable, not contain a key")
    return value


@dataclass(frozen=True)
class Configuration:
    source: Path
    data: dict

    @classmethod
    def from_mapping(cls, raw, source):
        x = copy.deepcopy(
            fields(
                raw,
                {
                    "version",
                    "name",
                    "paths",
                    "tasks",
                    "harnesses",
                    "actor",
                    "user",
                    "judge",
                    "execution",
                    "experience",
                },
                "configuration",
            )
        )
        if type(x.get("version")) is not int or x.get("version") != 1:
            raise ConfigurationError("version must be 1")
        x.setdefault("name", "harbor-evaluation")
        if not isinstance(x["name"], str) or not x["name"].strip():
            raise ConfigurationError("name must be nonempty")
        paths = fields(x.setdefault("paths", {}), {"harnesses", "cache", "runs"}, "paths")
        for k, v in {
            "harnesses": "../harnesses",
            "cache": ".cache",
            "runs": "runs",
        }.items():
            paths.setdefault(k, v)
            if not isinstance(paths[k], str) or not paths[k]:
                raise ConfigurationError("paths." + k + " must be a path")
        names = x.setdefault("harnesses", ["v0", "u32"])
        if (
            not isinstance(names, list)
            or not names
            or any(not isinstance(n, str) for n in names)
            or len(set(names)) != len(names)
            or any(n not in HARNESS_NAMES for n in names)
        ):
            raise ConfigurationError(
                "harnesses must be unique names from " + ", ".join(HARNESS_NAMES)
            )
        tasks = x.setdefault("tasks", "published38")
        if not isinstance(tasks, list) and tasks not in ["published38", "all"]:
            raise ConfigurationError("tasks must be published38, all, or a list of task names")
        if isinstance(tasks, list) and (
            not tasks or any(not isinstance(t, str) for t in tasks) or len(set(tasks)) != len(tasks)
        ):
            raise ConfigurationError("task names must be a nonempty unique list")
        actor = fields(
            x.setdefault("actor", {}),
            {
                "model",
                "base_url",
                "api_key_env",
                "anthropic_base_url",
                "anthropic_api_key_env",
                "reasoning_effort",
                "max_output_tokens",
                "stream",
                "thinking",
            },
            "actor",
        )
        actor.setdefault("model", "glm-5.3-flash")
        if not isinstance(actor["model"], str) or not actor["model"]:
            raise ConfigurationError("actor.model required")
        actor["base_url"] = endpoint(actor.get("base_url"), "actor.base_url")
        actor["api_key_env"] = env_name(
            actor.get("api_key_env", "ACTOR_API_KEY"), "actor.api_key_env"
        )
        actor["anthropic_base_url"] = endpoint(
            actor.get("anthropic_base_url"), "actor.anthropic_base_url", True
        )
        actor["anthropic_api_key_env"] = env_name(
            actor.get("anthropic_api_key_env", actor["api_key_env"]),
            "actor.anthropic_api_key_env",
        )
        actor.setdefault("reasoning_effort", "max")
        actor.setdefault("max_output_tokens", 65536)
        if actor["reasoning_effort"] not in {"none", "low", "medium", "high", "max"}:
            raise ConfigurationError("Invalid actor.reasoning_effort")
        positive(actor["max_output_tokens"], "actor.max_output_tokens")
        actor.setdefault("stream", "native")
        if actor["stream"] != "native" and type(actor["stream"]) is not bool:
            raise ConfigurationError("actor.stream must be native, true or false")
        actor.setdefault("thinking", True)
        boolean(actor["thinking"], "actor.thinking")
        if "claude-code" in names:
            if actor["stream"] != "native":
                raise ConfigurationError(
                    "Claude Code requires actor.stream: native; streaming is controlled by its CLI"
                )
            if actor["reasoning_effort"] == "none":
                raise ConfigurationError("Claude Code does not accept reasoning_effort: none")
        if "meta-harness" in names and actor["stream"] is True:
            raise ConfigurationError(
                "The pinned Meta-Harness consumes complete responses; actor.stream cannot be true"
            )
        user = fields(
            x.setdefault("user", {}),
            {
                "enabled",
                "model",
                "base_url",
                "api_key_env",
                "reasoning_effort",
                "max_output_tokens",
            },
            "user",
        )
        user.setdefault("enabled", True)
        boolean(user["enabled"], "user.enabled")
        user.setdefault("model", "glm-5.3-flash")
        if not isinstance(user["model"], str) or not user["model"]:
            raise ConfigurationError("user.model required")
        user["base_url"] = endpoint(user.get("base_url", actor["base_url"]), "user.base_url")
        user["api_key_env"] = env_name(
            user.get("api_key_env", actor["api_key_env"]), "user.api_key_env"
        )
        user.setdefault("reasoning_effort", "max")
        user.setdefault("max_output_tokens", 65536)
        if user["reasoning_effort"] not in {"none", "low", "medium", "high", "max"}:
            raise ConfigurationError("Invalid user.reasoning_effort")
        positive(user["max_output_tokens"], "user.max_output_tokens")
        judge = fields(x.setdefault("judge", {}), {"base_url", "api_key_env"}, "judge")
        judge["base_url"] = endpoint(judge.get("base_url"), "judge.base_url", True)
        judge["api_key_env"] = env_name(
            judge.get("api_key_env", "JUDGE_API_KEY"), "judge.api_key_env"
        )
        execution = fields(
            x.setdefault("execution", {}),
            {"provider", "concurrency", "repetitions", "time_adaptation"},
            "execution",
        )
        execution.setdefault("provider", "e2b")
        if execution["provider"] != "e2b":
            raise ConfigurationError(
                "This release supports E2B, matching the simulated-user execution protocol"
            )
        execution.setdefault("concurrency", 4)
        positive(execution["concurrency"], "execution.concurrency")
        execution.setdefault("repetitions", 1)
        positive(execution["repetitions"], "execution.repetitions")
        execution.setdefault("time_adaptation", False)
        boolean(execution["time_adaptation"], "execution.time_adaptation")
        exp = fields(x.setdefault("experience", {}), {"timeout_seconds"}, "experience")
        exp.setdefault("timeout_seconds", 600)
        positive(exp["timeout_seconds"], "experience.timeout_seconds")
        return cls(Path(source).resolve(), x)

    def path(self, name):
        p = Path(self.data["paths"][name]).expanduser()
        return p.resolve() if p.is_absolute() else (self.source.parent / p).resolve()

    def task_names(self):
        from .benchmarks.harbor_index.source import PIN

        names = self.data["tasks"]
        if names == "all":
            names = list(PIN["tasks"])
        elif names == "published38":
            import json

            names = json.loads(Path(__file__).with_name("published_tasks.json").read_text())
        unknown = set(names) - set(PIN["tasks"])
        if unknown:
            raise ConfigurationError("Unknown task names: " + ", ".join(sorted(unknown)))
        return list(names)

    def validate_sources(self):
        folder = {"claude-code": "Claude-Code", "meta-harness": "Meta-Harness"}
        for name in self.data["harnesses"]:
            if name == "claude-code":
                continue
            p = self.path("harnesses") / folder.get(name, name)
            marker = "agent.py" if name == "meta-harness" else "entry.py"
            if not (p / marker).is_file():
                raise ConfigurationError(f"Missing {name} source: {p / marker}")
        self.task_names()


def load(path="evaluation.yaml"):
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text())
    except OSError as exc:
        raise ConfigurationError(f"Cannot read {path}") from exc
    return Configuration.from_mapping(data, path)
