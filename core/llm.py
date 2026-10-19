import json, urllib.request, urllib.error
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CFG=json.loads((ROOT/'config'/'studio.json').read_text(encoding='utf-8'))['llm']

def _request(path, method='GET', payload=None):
    url=CFG['base_url'].rstrip('/')+path
    data=None if payload is None else json.dumps(payload).encode('utf-8')
    headers={'Content-Type':'application/json','Authorization':'Bearer '+CFG.get('api_key','local')}
    req=urllib.request.Request(url,data=data,headers=headers,method=method)
    with urllib.request.urlopen(req,timeout=CFG.get('timeout_seconds',600)) as r:
        return json.loads(r.read().decode('utf-8'))

def health():
    models=_request('/models')
    return {'ok':True,'base_url':CFG['base_url'],'models':[x.get('id') for x in models.get('data',[])]}

def chat(system,user):
    payload={'model':CFG['model'],'messages':[{'role':'system','content':system},{'role':'user','content':user}],'temperature':0.2}
    x=_request('/chat/completions','POST',payload)
    return x['choices'][0]['message']['content']
