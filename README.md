# Room routing research artifact — reviewer edition

This is the complete sealed anonymized research snapshot, including the earlier evidence and both later supplements. Everything is already expanded into the repository; no ZIP files or previous packages are needed. Original Git history is excluded, and this repository starts with an anonymous-author commit.

## Reading order

1. [Original artifact guide](reviewer_provenance/README.source.md): methods, baseline evidence, commands and limitations.
2. [First evidence supplement](delta_20261020/): retained decomposition and follow-up analyses.
3. [Latest evidence supplement](delta2_20261020/DELTA2.md), including stages A, B and C. Their incomplete or blocked experiments remain explicitly labelled.
4. [Claims](docs/CLAIMS.md), [verification evidence](docs/VERIFICATION.json), and the stage-specific numeric provenance and manifests.

`CANDIDATE_STATUS.json` is a historical preparation record. Later executed checks are documented in `docs/VERIFICATION.json`; the supplements retain their own scope and limitations. No new scientific GO decision is made by this upload.

## Obtain the full contents

Install Git LFS, clone this repository with Git, then run:

```text
git lfs install --local
git lfs pull
python verify_reviewer_files.py
```

Two large trace files use Git LFS and share one content object. Their actual bytes are required for a complete checkout. A GitHub web download or an AI connector may supply pointer files. On Windows enable long paths and use a short clone destination.

## Offline reproduction

Use Python 3.11 or 3.12 and install `repro/requirements.lock` before going offline. The existing runtime qualifications in the original guide still apply.

```text
python -m pip install -r repro/requirements.lock
python repro/run_all.py --replay
```

This replays retained data without model calls. The original guide lists tests and differential checks. Historical numeric results and raw data are preserved unchanged. One legacy project label in a metadata proof is anonymized, with its manifest repinned; the exact source/export hashes and reasons are recorded in `REVIEWER_SOURCE_INDEX.json`. This landing page and Git LFS attributes are adapted, with their exact originals retained in `reviewer_provenance/`. `REVIEWER_MANIFEST.sha256` covers the published files; `REVIEWER_RELEASE.json` describes the release checks.

File anonymization does not hide a hosting account, repository URL, hosting activity or linked account profile. For a blinded submission, follow the venue's anonymous artifact-access procedure.
