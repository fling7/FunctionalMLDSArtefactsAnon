"""Exact, append-only WP4 source amendments; no wildcard hash exemptions."""
from __future__ import annotations
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

AMENDMENT_SCHEMA = 'wp4-source-amendment-v1'
AMENDMENT_DIRECTORY = 'prereg/wp4_amendments'
UPDATABLE = frozenset({
    'experiments/lib/wp4_common.py', 'experiments/routing_baselines.py',
    'experiments/guarded_llm_turns.py', 'experiments/analyze_wp4.py',
    'repro/budget.py', 'repro/llm.py',
})
FORBIDDEN_ADDITION_PREFIXES = ('backend/', 'verification/impl_', 'experiments/prompts/')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def relative_file(root, relative):
    """Reject absolute paths, traversal and symlink escape in research manifests."""
    if not isinstance(relative, str) or '\\' in relative:
        raise RuntimeError('Manifest path must be a canonical relative POSIX path')
    name = PurePosixPath(relative)
    if name.is_absolute() or not name.parts or any(x in ('..', '.') for x in name.parts) or ':' in relative or str(name) != relative:
        raise RuntimeError('Unsafe manifest path: ' + relative)
    root = Path(root).resolve()
    path = root.joinpath(*name.parts)
    if not path.resolve().is_relative_to(root):
        raise RuntimeError('Manifest path escapes workspace: ' + relative)
    return path


def checked_file(root, relative, expected):
    if not isinstance(expected, str) or not re.fullmatch(r'[0-9a-fA-F]{64}', expected):
        raise RuntimeError('Invalid SHA256 for ' + str(relative))
    path = relative_file(root, relative)
    if not path.is_file() or digest(path).lower() != expected.lower():
        raise RuntimeError('Frozen artifact changed or missing: ' + relative)
    return path


def frozen_json(root, relative, expected=None):
    path = relative_file(root, relative)
    sidecar = path.with_suffix('.sha256')
    if not sidecar.is_file():
        raise RuntimeError('Missing freeze sidecar: ' + relative)
    words = sidecar.read_text(encoding='utf-8-sig').split()
    if not words:
        raise RuntimeError('Empty freeze sidecar: ' + relative)
    checked_file(root, relative, words[0])
    if expected is not None:
        checked_file(root, relative, expected)
    return read_json(path), digest(path)


def verify_effective_sources(root):
    """Check original plans, every exact reviewed overlay and all effective files.

    Drafts never apply. A newly changed implementation cannot run against the
    unamended base registry; it remains blocked until an overlay is frozen.
    """
    root = Path(root)
    plan, prior = frozen_json(root, 'prereg/wp4_plan.json')
    questions, question_hash = frozen_json(root, 'prereg/wp4_questions_plan.json')
    if plan.get('question_plan') != questions:
        raise RuntimeError('Question plan differs from the original embedded plan')
    effective = dict(plan['source_sha256'])
    for relative, expected in questions.get('code_sha256', {}).items():
        if effective.get(relative) != expected:
            raise RuntimeError('Original question source pin differs: ' + relative)
    chain = []
    originals = {}
    active_policy = None
    directory = root / AMENDMENT_DIRECTORY
    paths = sorted(p for p in directory.glob('*.json') if re.fullmatch(r'\d{3}_[a-z0-9_]+\.json', p.name))
    for sequence, path in enumerate(paths, 1):
        relative = path.relative_to(root).as_posix()
        amendment, pin = frozen_json(root, relative)
        if amendment.get('schema') != AMENDMENT_SCHEMA or amendment.get('sequence') != sequence or not path.name.startswith(f'{sequence:03d}_'):
            raise RuntimeError('Invalid WP4 amendment sequence/schema')
        if amendment.get('prior_freeze_sha256') != prior or amendment.get('base_question_plan_sha256') != question_hash:
            raise RuntimeError('WP4 amendment chain does not match original plans')
        for name, update in amendment.get('implementation_updates', {}).items():
            relative_file(root, name)
            if name not in UPDATABLE or effective.get(name) != update.get('old_sha256'):
                raise RuntimeError('Unapproved path or prior hash in WP4 amendment: ' + name)
            snapshot = update.get('original_snapshot')
            checked_file(root, snapshot, update['old_sha256'])
            originals[snapshot] = update['old_sha256']
            effective[name] = update['new_sha256']
        for name, pin_new in amendment.get('added_sources', {}).items():
            relative_file(root, name)
            if name in effective or name.startswith(FORBIDDEN_ADDITION_PREFIXES):
                raise RuntimeError('Invalid or duplicate added dependency: ' + name)
            effective[name] = pin_new
        policy = amendment.get('corpus_policy')
        if policy is not None:
            if active_policy is not None:
                raise RuntimeError('A001 corpus selection cannot be silently superseded')
            if policy.get('schema') != 'wp4-expanded-corpus-policy-v1' or policy.get('target_distinct_sources') != 20:
                raise RuntimeError('Invalid expanded corpus policy')
            if policy.get('allow_source_authoring_repair') is not True or policy.get('max_source_authoring_attempts') != 2:
                raise RuntimeError('Invalid approved source repair policy')
            if policy.get('extension_plan_path') != 'prereg/wp5_extension_v1/plan.json' or policy.get('source_freeze_manifest_path') != 'prereg/wp5_extension_v1/accepted_sources.json':
                raise RuntimeError('Unexpected two-stage extension artifact path')
            checked_file(root, policy['extension_plan_path'], policy.get('extension_plan_sha256'))
            frozen_json(root, policy['extension_plan_path'], policy['extension_plan_sha256'])
            checked_file(root, policy['accepted_sources_schema_path'], policy['accepted_sources_schema_sha256'])
            active_policy = policy
        chain.append({'path': relative, 'sha256': pin, 'sequence': sequence})
        prior = pin
    if chain and 'experiments/lib/wp4_amendments.py' not in effective:
        raise RuntimeError('Amendment verifier itself must be frozen')
    if active_policy and 'experiments/lib/wp4_selection.py' not in effective:
        raise RuntimeError('Expanded selection adapter must be frozen')
    for relative, expected in effective.items():
        checked_file(root, relative, expected)
    return {**plan, '_effective_source_sha256': effective, '_source_amendments': chain,
            '_original_source_snapshots': originals, '_corpus_policy': active_policy,
            '_effective_freeze_sha256': prior, '_question_plan_sha256': question_hash}


def archived_dependencies(plan):
    names = dict(plan['_effective_source_sha256'])
    names.update(plan['_original_source_snapshots'])
    return names
