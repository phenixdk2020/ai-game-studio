import json,urllib.request,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];CFG_PATH=ROOT/'config'/'studio.json'
def cfg():return json.loads(CFG_PATH.read_text(encoding='utf-8-sig'))
def request(path,method='GET',payload=None,timeout=8):
 c=cfg()['llm'];data=None if payload is None else json.dumps(payload).encode();h={'Content-Type':'application/json','Authorization':'Bearer '+c.get('api_key','local')};q=urllib.request.Request(c['base_url'].rstrip('/')+path,data=data,headers=h,method=method)
 with urllib.request.urlopen(q,timeout=timeout) as r:return json.loads(r.read().decode())
def models():return [x.get('id') for x in request('/models').get('data',[]) if x.get('id')]
def route(role):
 c=cfg()['llm'];profile=c['routing'].get(role,'light');return profile,c['models'][profile]
def chat(role,system,user):
 c=cfg()['llm'];profile,model=route(role);start=time.time();payload={'model':model,'messages':[{'role':'system','content':system},{'role':'user','content':user}],'temperature':0.2}
 x=request('/chat/completions','POST',payload,c.get('timeout_seconds',600));return x['choices'][0]['message']['content'],model,round(time.time()-start,1)
