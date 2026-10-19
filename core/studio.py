import argparse,json,uuid,threading,datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from runtime import chat,models,route,cfg
ROOT=Path(__file__).resolve().parents[1];Q=ROOT/'tasks'/'queue.json';R=ROOT/'results';A=ROOT/'agents';LOG=ROOT/'logs'/'studio.log';heavy_lock=threading.Lock();write_lock=threading.Lock()
def ensure_state():
 (ROOT/'tasks').mkdir(exist_ok=True);R.mkdir(exist_ok=True);LOG.parent.mkdir(exist_ok=True)
def log(msg):
 ensure_state();stamp=datetime.datetime.now().isoformat(timespec='seconds');print(msg,flush=True);open(LOG,'a',encoding='utf-8').write(f'{stamp} {msg}\n')
def load():ensure_state();return json.loads(Q.read_text(encoding='utf-8-sig')) if Q.exists() else []
def save(x):
 ensure_state()
 with write_lock:Q.write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')
def add(title,role,desc,deps=None):
 x={'id':str(uuid.uuid4())[:8],'title':title,'role':role,'description':desc,'dependencies':deps or [],'status':'queued','result_file':'','error':'','model':'','started':'','finished':''};a=load();a.append(x);save(a);return x
def plan(name):
 h=add('Historisk research: '+name,'historical_research','Historiske krav, kildebehov, usikkerheder og asset/gameplay-konsekvenser.');t=add('Teknisk research: '+name,'technical_research','Unreal 5.7 arkitektur og implementeringsvalg.');c=add('Character/3D: '+name,'character3d','Blender mesh/material/skeleton-spec.',[h['id']]);r=add('Rigging: '+name,'rigging','Bones, skinning, sockets og IK.',[c['id']]);a=add('Animation: '+name,'animation','Locomotion, actions og retargeting.',[r['id']]);g=add('Gameplay: '+name,'gameplay','Implementerbar gameplay-plan.',[h['id'],t['id']]);u=add('Unreal integration: '+name,'unreal','Import/integration i Unreal 5.7.',[g['id'],a['id']]);q=add('QA: '+name,'qa','Reproducerbar testplan.',[u['id']]);return[h,t,c,r,a,g,u,q]
def run_task(t):
 profile,model=route(t['role']);log(f'[START] {t["id"]} {t["role"]} model={model} profile={profile}');system=(A/(t['role']+'.md')).read_text(encoding='utf-8');deps=[]
 for d in t.get('dependencies',[]):
  p=R/(d+'.md');deps.append({'task_id':d,'result':p.read_text(encoding='utf-8-sig') if p.exists() else ''})
 def work():return chat(t['role'],system,json.dumps({'task':t,'dependencies':deps},ensure_ascii=False,indent=2))
 try:
  if profile=='heavy':
   log(f'[HEAVY] {t["id"]} waiting/acquiring heavy slot')
   with heavy_lock:out,used,secs=work()
  else:out,used,secs=work()
  p=R/(t['id']+'.md');p.write_text(out,encoding='utf-8');log(f'[DONE] {t["id"]} {secs}s -> {p}');return t['id'],'done',str(p),'',used
 except Exception as e:log(f'[FAIL] {t["id"]} {e}');return t['id'],'failed','',str(e),model
def run_layer():
 rows=load();st={x['id']:x['status'] for x in rows};ready=[x for x in rows if x['status']=='queued' and all(st.get(d)=='done' for d in x.get('dependencies',[]))];log(f'[READY] {len(ready)} task(s)')
 if not ready:return 0
 now=datetime.datetime.now().isoformat(timespec='seconds')
 for x in rows:
  if any(x['id']==r['id'] for r in ready):x['status']='running';x['started']=now
 save(rows)
 with ThreadPoolExecutor(max_workers=max(2,cfg().get('max_parallel_light',2))) as ex:
  fs=[ex.submit(run_task,x) for x in ready];res={}
  for f in as_completed(fs):i,s,o,e,m=f.result();res[i]=(s,o,e,m)
 rows=load()
 for x in rows:
  if x['id'] in res:x['status'],x['result_file'],x['error'],x['model']=res[x['id']];x['finished']=datetime.datetime.now().isoformat(timespec='seconds')
 save(rows);return len(ready)
def run_all():
 layer=1
 while True:
  log(f'=== LAYER {layer} ===');n=run_layer()
  if not n:break
  if any(x['status']=='failed' for x in load()):log('[STOP] Failed task detected.');break
  layer+=1
 log('[COMPLETE] No more ready tasks.')
def status():
 rows=load()
 if not rows:print('No queue yet. Use plan only for a NEW project/feature.')
 for x in rows:print(f"{x['id']} | {x['status']:<8} | {x['role']:<20} | {x.get('model',''):<28} | {x['title']}")
def setup():print(json.dumps({'version':cfg()['version'],'models':models(),'routing':cfg()['llm']['routing']},indent=2))
def recover():
 x=load();changed=0
 for t in x:
  if t['status']=='running':t['status']='queued';t['error']='Recovered after interrupted run';changed+=1
 save(x);print('Recovered',changed,'running task(s).')
def reset_failed():
 x=load()
 for t in x:
  if t['status']=='failed':t.update(status='queued',error='',result_file='',model='',started='',finished='')
 save(x)
if __name__=='__main__':
 p=argparse.ArgumentParser();s=p.add_subparsers(dest='cmd',required=True);a=s.add_parser('plan');a.add_argument('feature');s.add_parser('run');s.add_parser('run-all');s.add_parser('status');s.add_parser('setup');s.add_parser('recover');s.add_parser('reset-failed');n=p.parse_args()
 if n.cmd=='plan':[print(x['id'],x['role']) for x in plan(n.feature)]
 elif n.cmd=='run':run_layer()
 elif n.cmd=='run-all':run_all()
 elif n.cmd=='status':status()
 elif n.cmd=='setup':setup()
 elif n.cmd=='recover':recover()
 else:reset_failed()
