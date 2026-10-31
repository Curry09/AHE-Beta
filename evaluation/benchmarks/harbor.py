"""Standard local Harbor task packages, with no benchmark-specific policy."""

from pathlib import Path


def task_names(selection):
    if (
        not isinstance(selection, list)
        or not selection
        or any(not isinstance(path, str) or not path.strip() for path in selection)
    ):
        raise ValueError("tasks must be a nonempty list of local Harbor task package paths")
    names = [Path(path).name for path in selection]
    if any(not name or name in {".", ".."} for name in names) or len(set(names)) != len(names):
        raise ValueError("Local Harbor task package directory names must be nonempty and unique")
    return names


def validate_configuration(data):
    task_names(data.get("tasks"))
    extra = set(data["judge"]) - {"base_url", "api_key_env"}
    if extra:
        raise ValueError(
            f"Standard Harbor packages do not support judge overrides {sorted(extra)}; "
            "the task package owns its grader settings"
        )


def resolve_dataset(dataset, source):
    from evaluation.config import CaseRef
    from evaluation.harbor.tasks import local_task_digest

    selections = dataset.get("task_paths")
    names = task_names(selections)
    cases = []
    for name, value in zip(names, selections, strict=True):
        root = Path(value).expanduser()
        if not root.is_absolute():
            root = Path(source).parent / root
        root = root.resolve()
        if not (root / "task.toml").is_file():
            raise ValueError(f"Local Harbor task package lacks task.toml: {root}")
        cases.append(CaseRef("Harbor", name, "local-package", local_task_digest(root), str(root)))
    return {"source": "harbor", "task_paths": [case.root for case in cases]}, tuple(cases)


def prepare_dataset(dataset):
    # Files already belong to the operator. Never download or rewrite them.
    resolve_dataset(dataset, Path.cwd() / "evaluation.yaml")


def prepare_cases(config, download=True):
    return resolve_dataset({"source": "harbor", "task_paths": config.data["tasks"]}, config.source)
