"""Install the Claude adapter without replacing newer GUI/worker implementations."""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import shutil


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--model', required=True)
    parser.add_argument('--claude', default=str(Path.home()/'.local/bin/claude.exe'))
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    target = args.root.resolve()
    if source == target:
        raise ValueError('Run installer from the reviewed source checkout')
    if not Path(args.claude).is_file() and not shutil.which(args.claude):
        raise ValueError('Claude Code executable not found')
    config = json.loads((target/'config/orchestrator.json').read_text(encoding='utf-8-sig'))
    config.update(claude_executable=args.claude,
                  claude_ollama={'base_url':'http://127.0.0.1:11434','model':args.model,
                                 'tool_capabilities':['image_generation','image_to_3d','animation'],
                                 'context_tokens':65536,'max_output_tokens':8192})
    backup = Path(os.environ.get('LOCALAPPDATA', Path.home()))/'AI-Game-Studio/backups'/('claude-ollama-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    copied = ['adapters/claude_ollama.py','adapters/project_bridge.py','adapters/studio_agent_tools.py',
              'adapters/Studio.AgentTools.Queue.ps1',
              'adapters/studio_projects.py','tools/agent_selector_v192.py','docs/claude-ollama.md']
    patched = ['adapters/Studio.Orchestrator.psm1','adapters/Studio.Gui.ps1','tools/studio.py']
    for rel in copied + patched + ['config/orchestrator.json']:
        path = target/rel
        if path.is_file():
            destination=backup/rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path,destination)
    for rel in copied:
        (target/rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source/rel,target/rel)
    for rel in patched:
        path = target/rel
        text = path.read_text(encoding='utf-8-sig')
        if "'claude-ollama'" not in text:
            text = text.replace("'copilot-local','copilot-github'", "'copilot-local','copilot-github','claude-ollama'")
            path.write_text(text,encoding='utf-8-sig' if path.suffix in {'.ps1','.psm1'} else 'utf-8')
    (target/'config/orchestrator.json').write_text(json.dumps(config,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({'installed':True,'backup':str(backup),'backend':'claude-ollama','model':args.model}))


if __name__ == '__main__':
    main()
