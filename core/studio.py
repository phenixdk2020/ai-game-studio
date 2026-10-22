"""Compatibility entry point: all execution uses the canonical studio CLI."""
import json
from pathlib import Path
import runpy

def load_queue(path):
    path=Path(path)
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else []

def ready_tasks(rows):
    statuses={x['id']:x['status'] for x in rows}
    return [x for x in rows if x['status']=='queued' and all(statuses.get(d)=='done' for d in x.get('dependencies',[]))]

if __name__=='__main__':
    runpy.run_path(str(Path(__file__).resolve().parents[1]/'tools/studio.py'),run_name='__main__')
