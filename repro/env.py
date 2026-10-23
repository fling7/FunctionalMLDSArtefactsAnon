"""Load local credentials without printing, persisting, or overriding them."""
from __future__ import annotations
import os
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

def load_env(root: Path = ROOT) -> dict[str, str]:
    path = root / '\x2eenv'
    if path.is_file():
        for raw in path.read_text(encoding='utf-8-sig').splitlines():
            line = raw.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            name, value = line.split('=', 1)
            name, value = name.strip(), value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            if name in {'OPENAI_API_KEY', 'OPENAI_API_KEY_FILE', 'MAX_API_COST_USD'}:
                os.environ.setdefault(name, value)
    if os.environ.get('OPENAI_API_KEY') and os.environ.get('OPENAI_API_KEY_FILE'):
        raise ValueError('Specify one credential source, not both environment key and key file.')
    return dict(os.environ)

def get_key() -> str:
    load_env()
    key = os.environ.get('OPENAI_API_KEY', '').strip()
    if not key and os.environ.get('OPENAI_API_KEY_FILE'):
        key = Path(os.environ['OPENAI_API_KEY_FILE']).read_text(encoding='utf-8-sig').strip()
    return key
