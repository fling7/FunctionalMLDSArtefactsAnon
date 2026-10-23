# Dependency compatibility

The observed experiment environment is Python3.12.8 on Windows. Its exact installed package versions are retained in repro/requirements-observed-py312.lock. The install lock uses Python-version markers for three packages whose observed versions require Python3.12, so the original unqualified lock could not satisfy the requested Python3.11 support.

For Python3.11, the compatibility pins are NumPy2.3.4, ContourPy1.3.3 and SciPy1.17.1. Their primary package metadata declares Python3.11 support:
- https://pypi.org/project/numpy/2.3.4/
- https://pypi.org/project/contourpy/1.3.3/
- https://pypi.org/project/scipy/1.17.1/

The complete install lock was installed successfully into an isolated workspace environment running CPython3.11.13 on Windows. A selected stable core suite passed 1,248 tests in 428.36 seconds. It covers guard modes, packet regression, real local HTTP transaction tests with unit model responses, publication, routing verification, budget/gateway behavior, structured rejection codes and both digest layers. These are engineering tests, not real-model scientific observations. Evidence: results/raw/python311_core_compat_20261015.xml, results/raw/python311_installed.lock and logs/python311_core_compat_20261015.log. Source changes after this run require their affected checks again.

The original Python3.12 environment passed the then-collected full suite: 1,363 tests in 1,394.97 seconds (results/raw/full_suite_pre_anonymity_20261015.xml). WP4 orchestration edits overlapped that run, so this is not a final frozen-amendment verification. Those changes have a separate targeted test run.

All 127 Python files in anonymous draft v4 parse with Python3.11 grammar. This establishes syntax compatibility only. The anonymous full suite and final artifact replay are separate pending gates.

Linux runtime verification remains unexecuted: WSL is not installed and no local Docker runtime is available. No Linux pass is claimed. Current research campaigns retain their original Python3.12 environment; no installed package was downgraded.

The replay lock additionally pins pypdf6.10.0 for deterministic page-only PDF cleanup. This matches the version used by the anonymous media exporter. Its installation and affected checks are recorded separately; earlier suite evidence predates this addition.
