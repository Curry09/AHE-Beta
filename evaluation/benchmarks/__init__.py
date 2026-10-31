"""Task sources and optional benchmark-specific support, separate from execution.

Profiles interpret the frozen runtime settings through environment_options and
verifier_env. Environment options are opaque to the generic worker/provider;
the profile's EnvironmentSupport consumes them on each environment instance.
Standard Harbor packages use a source module for YAML acquisition but have no
benchmark-specific runtime profile and receive neither runtime extension.
Source modules validate_configuration, task_names and prepare_cases for the
public YAML entry; catalog/model rules never belong to the generic parser.
validate_configuration normalizes only source-owned fields after common type
and credential-reference checks. prepare_cases acquires materials, not agents.
"""

from importlib import import_module

_SOURCES = {
    "harbor_index": ("Harbor Index", "evaluation.benchmarks.harbor_index.profile"),
    "harbor": ("Harbor", "evaluation.benchmarks.harbor"),
}
DEFAULT_SOURCE = "harbor_index"


def configuration_profile(name):
    if not isinstance(name, str) or name not in _SOURCES:
        raise ValueError("Unknown task_source; choose from " + ", ".join(sorted(_SOURCES)))
    return import_module(_SOURCES[name][1])


def get_profile(benchmark):
    if benchmark == "Harbor":
        return None
    for label, module in _SOURCES.values():
        if label == benchmark:
            return import_module(module)
    raise ValueError(f"Unknown task source: {benchmark}; use Harbor for a standard task package")


def dataset_profile(dataset):
    name = dataset.get("source", DEFAULT_SOURCE)
    if not isinstance(name, str) or name not in _SOURCES:
        raise ValueError(
            "Unknown dataset source; use explicit cases for a standard Harbor task package"
        )
    return import_module(_SOURCES[name][1])


def resolve_dataset(dataset, source):
    return dataset_profile(dataset).resolve_dataset(dataset, source)


def prepare_dataset(dataset):
    dataset_profile(dataset).prepare_dataset(dataset)
