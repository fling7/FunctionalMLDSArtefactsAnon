"""Portable report replay using an explicit, shipped release registry.

This entry does not infer research completeness from successful regeneration.
It uses the unchanged previously tested offline executor and network guard.
"""
from pathlib import Path
import argparse
import json
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from repro import replay_executor


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--replay', action='store_true')
    mode.add_argument('--offline', action='store_true')
    mode.add_argument('--llm', action='store_true')
    parser.add_argument('--manifest', default='data/replay/release_registry.json')
    parser.add_argument('--output')
    args = parser.parse_args(argv)
    if args.llm:
        parser.error('Paid experiments require their registered experiment runners.')
    manifest = replay_executor.safe(ROOT, args.manifest)
    if not manifest.is_file():
        parser.error('Release registry is not present; full release replay is not ready.')
    registry = json.loads(manifest.read_text(encoding='utf-8'))
    replay_executor.validate(ROOT, registry, False)
    destination = replay_executor.safe(ROOT, args.output or 'results/replay/release_' + uuid.uuid4().hex)
    if not destination.is_relative_to(ROOT / 'results/replay'):
        parser.error('Output must stay in results/replay.')
    if destination.exists():
        parser.error('Output already exists; prior evidence is preserved.')
    result = replay_executor.execute(ROOT, registry, destination, False)
    print(json.dumps({'status': result['status'], 'output': destination.relative_to(ROOT).as_posix(),
                      'scope': 'Only the exact reports and inputs declared in the shipped registry.',
                      'scientific_gates': 'Assessed separately; successful replay is not a scientific PASS.'}))
    return 0 if result['status'] == 'complete' else 1


if __name__ == '__main__':
    raise SystemExit(main())
