"""One-command offline current data replay; historical sealed replay remains available."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
if '--legacy-replay' in sys.argv:
 sys.argv.remove('--legacy-replay')
 from repro.completed_replay import main
else:
 from repro.sprint_report import main
if __name__=='__main__':raise SystemExit(main())
