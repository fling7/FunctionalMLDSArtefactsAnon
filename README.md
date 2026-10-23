# Model-based routing in multi-agent rooms

In a virtual room with several conversational agents, a request about an object needs to reach an agent responsible for that object. This repository implements routing checks based on a room model: who owns an object, which handoffs are allowed, and which action an agent may execute. It also checks whether the model has changed before a response is committed.

The repository contains the backend, two separately implemented evaluators, experimental data, and scripts for reproducing the reported results. The [specification](docs/SPEC.md) defines the routing rules. [Claims and evidence](docs/CLAIMS.md) connects the research claims to the experiments.

## Reproduce the results

You need Python 3.11 or 3.12 and Git LFS. After cloning the repository, run these commands from its root directory:

```sh
git lfs install --local
git lfs pull
python verify_reviewer_files.py
```

Git LFS downloads the two large trace files. The Python script checks the downloaded files against their recorded checksums. On Windows, enable long paths and use a short destination path when cloning.

Install the Python dependencies and run the report:

```sh
python -m pip install -r repro/requirements.lock
python repro/run_all.py --replay
```

The replay verifies saved model requests and responses, recomputes routing outcomes, and rebuilds the result tables and figures. It writes `numbers.json`, CSV tables, and PDF/SVG figures to `results/replay/go_sprint/`. Once the dependencies are installed, it runs offline and sends no new requests to language models.

## Repository contents

| Path | Contents |
|---|---|
| [`app/backend_root/agent_backend/`](app/backend_root/agent_backend/) | Backend and request handling |
| [`tools/`](tools/) | Model validation and routing-table construction |
| [`verification/`](verification/) | Reference evaluators and differential checks |
| [`tests/`](tests/) | Regression tests and fixtures |
| [`data/`](data/) | Experiment inputs and saved model responses |
| [`results/`](results/) | Experiment records and computed results |
| [`repro/`](repro/) | Reporting and reproduction scripts |
| [`docs/`](docs/) | Specification, methods, claims, and limitations |

## Experiments

The main mutation study contains 908 generated mutants and 153 mutants from the classroom case. These cohorts are reported separately. Of the generated mutants, 198 were rejected during backend setup; their refusal records are included in the data.

Further analyses are documented in two reports:

- [Ablations, property checks, and pipeline refusals](delta_20261020/DELTA.md).
- [Runtime measurements and additional mutation and prompting experiments](delta2_20261020/DELTA2.md).

The second report also identifies experiments that were only partly completed or could not be run. Use its stated sample sizes when interpreting those results.

The routing checks enforce the declarations in a room model. They do not establish whether those declarations reflect a visitor's intent or whether an agent's answer is correct. Known disagreements between the backend and the specification are discussed in [DISAGREEMENTS.md](docs/DISAGREEMENTS.md).

## Run the tests

```sh
python -m pytest -q tests
python repro/differential_full.py --run-id local_main
python repro/differential_full.py --extended-only --run-id local_extended
```

The two differential runs compare the backend with the reference evaluators across all 17 request variants. Recorded Windows runs with Python 3.12 produced subprocess diagnostics despite passing test assertions. The tested environments and results are documented in [VERIFICATION.json](docs/VERIFICATION.json).

## License

The code is distributed under the [MIT License](LICENSE). Dependencies retain their own licenses.
