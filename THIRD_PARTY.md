# Third-party sources and licenses

English | [简体中文](THIRD_PARTY.zh-CN.md)

The root [MIT License](LICENSE) applies to auto-designer's original code and contributions licensed under those terms. Third-party code, dependencies and research materials retain their own licenses, copyright notices and attribution. This document identifies their sources and explains how they relate to the project's license.

## Code and dependencies

| Component | Source and version | License and attribution |
| --- | --- | --- |
| NexAU | [hzhua/nexau](https://github.com/hzhua/nexau), commit `28511d9f0362191a6c378fd441b2be55309a9e32` | [Apache-2.0](https://github.com/hzhua/nexau/blob/28511d9f0362191a6c378fd441b2be55309a9e32/LICENSE). Installed as a pinned Git dependency; its license and notices remain applicable. |
| Bundled Spec tools | [Curry09/OpenAgents](https://github.com/Curry09/OpenAgents); files under `tools/spec-driven-development/` | MIT. The bundled copy retains the [OpenAgents license](tools/spec-driven-development/vendor/LICENSE). |
| Meta-Harness artifact | [stanford-iris-lab/meta-harness-tbench2-artifact](https://github.com/stanford-iris-lab/meta-harness-tbench2-artifact), commit `57fefdb2ff84af3fd81b69d67814acbe69bd0743` | The bundled snapshot has no separate license file or license declaration in its package metadata. The project's MIT license does not grant rights to these upstream files. See the attribution and modification records below. |
| Other Python and frontend dependencies | Versions and sources are recorded in [uv.lock](uv.lock), [evaluation/requirements.lock](evaluation/requirements.lock) and [frontend/package-lock.json](frontend/package-lock.json) | Each dependency retains its own license. Installing or bundling a dependency does not change its license to MIT. |

The Meta-Harness snapshot is stored in `evaluation/harness/meta_artifact/`. Its [upstream README](evaluation/harness/meta_artifact/README.md) credits Terminus-KIRA by KRAFTON AI and Harbor's Terminus-2 framework. The [provenance record](evaluation/harness/meta_artifact/provenance.json) identifies the upstream revision, file hashes and compatibility changes made for this project.

## Runtime distributions

Evaluation runtime archives contain pinned CPython and NexAU materials. Their upstream licenses and notices apply to the included components. Claude Code is installed from its official versioned distribution and remains subject to its own terms.

When redistributing NexAU, include its Apache-2.0 license and applicable copyright and attribution notices. Preserve upstream `NOTICE` content where provided, and identify changes to modified upstream files. These requirements also apply when NexAU is included in a runtime archive or container image.

## Task and benchmark materials

Task packages, benchmark definitions, source repositories, tests, datasets and container images may have different upstream licenses. The project's MIT license applies to its own integration code and does not replace those terms.

- [Evolution task materials](examples/tasks/evolution32/README.md) include scenarios from SWE-bench, Terminal-Bench, TUA-Bench, NL2Repo and project-specific tasks. Their [manifest](examples/tasks/evolution32/manifest.json), task definitions and provenance records identify the inputs, source revisions, hashes and images.
- [Harbor evaluation](evaluation/README.md) uses task sources configured through `evaluation.yaml`. Harbor Index source information is recorded under [evaluation/benchmarks/harbor_index/](evaluation/benchmarks/harbor_index/); other Harbor task packages retain the terms supplied with those packages.
- [Historical research materials](research/README.md) retain the sources and versions recorded in their archives and inventory.

Availability through a public repository, registry or Release does not by itself grant a license to third-party material. Refer to the terms supplied with the specific source code, dataset, task or image when using or redistributing it.

## Personas and source references

[Persona examples](examples/personas/) and the [persona extraction tools](tools/persona-distill/) contain descriptions derived from public developer profiles, writings and other referenced sources. Original quotations, code and other source material retain their respective rights. References identify the basis for a simulated persona; they do not imply that the person participated in or endorsed an experiment.

The [offline demo](backend/auto_designer/user/sim/demo.py) uses synthetic personas and scripted responses.

## Experiment records and model output

Experiment records can include third-party task code, source data, conversations and generated output. Their inclusion in an experiment does not change the rights or terms associated with the underlying material. The project's MIT license does not grant blanket rights to those contents. Guidance on handling private information is in [SECURITY.md](SECURITY.md).
