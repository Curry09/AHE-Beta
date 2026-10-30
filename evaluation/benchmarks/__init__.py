"""Task sources and optional benchmark-specific support, separate from execution."""

from importlib import import_module

_SOURCES = {
    "harbor_index": ("Harbor Index", "evaluation.benchmarks.harbor_index.profile"),
}


def get_profile(benchmark):
    if benchmark == "Harbor":
        return None
    for label, module in _SOURCES.values():
        if label == benchmark:
            return import_module(module)
    raise ValueError(f"Unknown task source: {benchmark}; use Harbor for a standard task package")


def dataset_profile(dataset):
    name = dataset.get("source", "harbor_index")
    if not isinstance(name, str) or name not in _SOURCES:
        raise ValueError(
            "Unknown dataset source; use explicit cases for a standard Harbor task package"
        )
    return import_module(_SOURCES[name][1])


def resolve_dataset(dataset, source):
    return dataset_profile(dataset).resolve_dataset(dataset, source)


def prepare_dataset(dataset):
    dataset_profile(dataset).prepare_dataset(dataset)
