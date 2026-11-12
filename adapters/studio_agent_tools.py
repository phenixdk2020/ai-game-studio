"""Task-scoped MCP interface to Studio's queue and registered Pinokio tools."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request
import urllib.parse
from datetime import datetime, timezone

from asset_pipeline import contained, read_json, write_json, task_lock
from local_project import safe_path


SCHEMAS = [
    ('studio_list_tools','List registered Studio tool operations and their parameters.',{}),
    ('studio_submit_tool','Queue and start an installed Pinokio tool for this project. Reuse the same request_key when retrying.',
     {'request_key':{'type':'string'},'capability':{'type':'string'},'operation':{'type':'string'},
      'title':{'type':'string'},'parameters':{'type':'object'}}),
    ('studio_tool_status','Read status, result and artifact metadata for your own tool task.',{'task_id':{'type':'string'}}),
    ('studio_wait_tool','Wait at most 25 seconds for your tool task, then return current status.',{'task_id':{'type':'string'}}),
    ('studio_copy_artifact','Copy a verified generated artifact into the isolated code checkout for final code review.',
     {'task_id':{'type':'string'},'artifact_index':{'type':'integer'},'destination':{'type':'string'}}),
]


class StudioTools:
    def __init__(self, context_path, spawn=True):
        self.context_path=Path(context_path).resolve()
        self.context=read_json(self.context_path)
        self.root=Path(self.context['root']).resolve()
        self.checkout=Path(self.context['checkout']).resolve()
        self.folder=self.context_path.parent
        self.spawn=spawn

    def check_parent(self):
        receipt=read_json(self.folder/'receipt.json')
        if (receipt.get('taskId')!=self.context['parent']['id'] or receipt.get('backend')!='claude-ollama'
                or receipt.get('sessionId')!=self.context['session'] or receipt.get('status')!='Running'):
            raise ValueError('This coding session is no longer active')

    def queue(self, action, task_id, **values):
        if action=='get':
            tasks=read_json(self.root/'tasks/queue.gui.json')
            if isinstance(tasks,dict):tasks=tasks.get('value',[])
            parent=next((t for t in tasks if t['id']==self.context['parent']['id']),None)
            task=next((t for t in tasks if t['id']==task_id),None)
            if not parent or parent.get('backend')!='claude-ollama':raise ValueError('Coding parent not found')
            if not task or task.get('requestedBy')!=parent['id'] or task.get('projectId')!=parent.get('projectId'):
                raise ValueError('Tool task does not belong to this coding task')
            return {'task':task}
        request=self.folder/('queue-call-'+os.urandom(8).hex()+'.json')
        write_json(request,dict(action=action,parent=self.context['parent']['id'],id=task_id,**values))
        shell=shutil.which('pwsh') or shutil.which('powershell.exe')
        if not shell:raise ValueError('PowerShell is required for the Studio queue writer')
        result=subprocess.run([shell,'-NoProfile','-File',str(Path(__file__).with_name('Studio.AgentTools.Queue.ps1')),
                               '-Root',str(self.root),'-Request',str(request)],capture_output=True,text=True,
                              encoding='utf-8',errors='replace',timeout=30)
        if result.returncode:raise ValueError(result.stderr.strip()[-2000:] or 'Queue operation failed')
        return json.loads(result.stdout)

    def catalog(self):
        catalog=read_json(self.root/'config/pinokio-tools.json')['tools']
        allowed=self.context['config'].get('claude_ollama',{}).get('tool_capabilities',[])
        return {key:value for key,value in catalog.items() if key in allowed and 'integration' in value['roles']}

    def parameters(self, value):
        if isinstance(value,dict):
            if set(value)=={'local_file'}:
                path=safe_path(self.checkout,value['local_file'])
                if not path.is_file():raise ValueError('Tool input file does not exist in the checkout')
                return {'local_file':str(path)}
            return {k:self.parameters(v) for k,v in value.items()}
        if isinstance(value,list):return [self.parameters(v) for v in value]
        return value

    def submit(self, args):
        key=args['request_key']
        if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',key):raise ValueError('Invalid request_key')
        catalog=self.catalog();cap=args['capability'];operation=args['operation']
        if cap not in catalog or operation not in ['inspect',*catalog[cap].get('operations',{})]:
            raise ValueError('Tool capability or operation is not registered/enabled')
        if not isinstance(args.get('parameters',{}),dict):raise ValueError('parameters must be an object')
        parameters=self.parameters(args.get('parameters',{}))
        parent=self.context['parent']
        identity=hashlib.sha256((parent['id']+'\n'+key).encode()).hexdigest()[:20].upper()
        task_id='TOOL-'+identity
        inputs=dict(capability=cap,operation=operation,parameters=parameters,title=args.get('title') or cap+' / '+operation)
        digest=hashlib.sha256(json.dumps(inputs,sort_keys=True).encode()).hexdigest()
        task=dict(schemaVersion=1,id=task_id,title=inputs['title'][:200],description='Tool requested by coding task '+parent['id'],
                  backend='pinokio',role='integration',agent='integration',kind='task',status='Running',
                  projectId=parent['projectId'],projectPath=parent.get('projectPath',''),attachments=[],dependencies=[],
                  priority=parent.get('priority',10),requestedBy=parent['id'],toolRequestDigest=digest,
                  toolCapability=cap,toolOperation=operation,toolParameters=parameters,
                  toolAppId=catalog[cap].get('preferred_app',''),pipelineStage='studio-tool-dispatch',
                  createdAt=datetime.now(timezone.utc).isoformat(),
                  question='Queued for the Studio tool executor; operator approval still applies to the result.')
        saved=self.queue('submit',task_id,task=task)
        if saved['created'] and self.spawn:
            try:
                output=self.folder/(task_id+'-executor.txt')
                with output.open('ab') as log:
                    subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--execute',task_id,'--context',str(self.context_path)],
                                     stdout=log,stderr=log,stdin=subprocess.DEVNULL,
                                     creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            except Exception as error:
                self.queue('update',task_id,update=dict(status='NeedsInput',error=str(error),question='Tool executor could not start; inspect existing task before retrying.'))
                raise
        # GPU generation must finish before Claude asks Ollama for more tokens.
        # Inspections can return immediately; they do not load generation models.
        if self.spawn and operation!='inspect':
            deadline=time.monotonic()+1800
            while self.status(task_id)['status'] in {'Running','Queued'}:
                if time.monotonic()>=deadline:break
                time.sleep(2)
        current=self.status(task_id)
        return dict(task_id=task_id,status=current['status'],created=saved['created'],
                    message='Use studio_wait_tool or studio_tool_status. Do not submit a second request key for the same operation.')

    def status(self, task_id):
        task=self.queue('get',task_id)['task']
        result={key:task.get(key,'') for key in ('id','status','title','pipelineStage','error','question')}
        result['review_required']=task['status']!='Completed'
        path=Path(task.get('resultPath') or self.folder/'missing-result')
        jobs=Path(self.context['config']['jobs_root'])
        if not jobs.is_absolute():jobs=self.root/jobs
        child=jobs/task_id/'bridge'
        if path.is_file() and path.resolve().is_relative_to(child.resolve()) and path.stat().st_size<=256_000:
            if path.suffix.lower()=='.json':result['result']=read_json(path)
            else:result['result']=path.read_text(encoding='utf-8-sig')
        return result

    def copy_artifact(self, args):
        status=self.status(args['task_id'])
        if status['status'] not in {'AwaitingVisualReview','Completed'}:raise ValueError('Tool has no completed result to import')
        data=status.get('result',{})
        if not isinstance(data,dict):raise ValueError('Tool has no artifact manifest')
        index=args['artifact_index']
        if type(index) is not int or index<0:raise ValueError('Invalid artifact index')
        artifact=data.get('artifacts',[])[index]
        source=Path(artifact['path'])
        jobs=Path(self.context['config']['jobs_root'])
        if not jobs.is_absolute():jobs=self.root/jobs
        contained(source,jobs/args['task_id']/'bridge')
        if source.stat().st_size>128*1024*1024:raise ValueError('Artifact exceeds 128 MiB')
        content=source.read_bytes()
        if hashlib.sha256(content).hexdigest()!=artifact['sha256']:raise ValueError('Artifact hash mismatch')
        task=self.queue('get',args['task_id'])['task']
        extensions=self.catalog()[task['toolCapability']]['operations'][task['toolOperation']].get('artifact_extensions',[])
        if source.suffix.lower() not in extensions:raise ValueError('Artifact type is not registered for this operation')
        destination=safe_path(self.checkout,args['destination'])
        if destination.suffix.lower()!=source.suffix.lower():raise ValueError('Preserve the artifact extension')
        if destination.exists():raise ValueError('Destination already exists; choose a new project path')
        destination.parent.mkdir(parents=True,exist_ok=True)
        audit=self.folder/'studio-tool-imports.json'
        imports=read_json(audit) if audit.exists() else []
        imports.append(dict(task_id=args['task_id'],destination=args['destination'],sha256=artifact['sha256']))
        write_json(audit,imports)
        with destination.open('xb') as output:output.write(content)
        return dict(path=destination.relative_to(self.checkout).as_posix(),sha256=artifact['sha256'],
                    review_required=True,message='Copied to isolated checkout only; review code and tool output before applying to original project.')

    def call(self, name, args):
        self.check_parent()
        if name=='studio_list_tools':return self.catalog()
        if name=='studio_submit_tool':return self.submit(args)
        if name=='studio_tool_status':return self.status(args['task_id'])
        if name=='studio_copy_artifact':return self.copy_artifact(args)
        if name=='studio_wait_tool':
            deadline=time.monotonic()+25
            while True:
                result=self.status(args['task_id'])
                if result['status'] not in {'Queued','Running'} or time.monotonic()>=deadline:return result
                time.sleep(1)
        raise ValueError('Unknown Studio tool')


def execute_child(service, task_id):
    from project_bridge import Bridge
    task=service.queue('get',task_id)['task']
    if task['status']!='Running':return
    config=service.context['config']
    jobs=Path(config['jobs_root'])
    if not jobs.is_absolute():jobs=service.root/jobs
    task_file=jobs/task_id/'bridge-task.json'
    task_file.parent.mkdir(parents=True,exist_ok=True)
    write_json(task_file,task)
    # One GPU tool executor at a time. A process crash releases the OS lock.
    lock_root=jobs/'.studio-tool-resource';lock_root.mkdir(exist_ok=True)
    deadline=time.monotonic()+1800
    while True:
        try:
            with task_lock(lock_root):
                if service.queue('get',task_id)['task']['status']!='Running':return
                if task['toolOperation']!='inspect':
                    selected=config['claude_ollama']
                    request=urllib.request.Request(selected['base_url'].rstrip('/')+'/api/generate',
                        data=json.dumps({'model':selected['model'],'keep_alive':0}).encode(),headers={'Content-Type':'application/json'})
                    with urllib.request.urlopen(request,timeout=120) as response:response.read()
                result=Bridge(task,config).advance(True)
                write_json(task_file,{**task,**result})
                # Release only our completed Comfy image job's cached models so Ollama can reload.
                if task['toolCapability']=='image_generation' and task['toolOperation']=='generate_image' and result['status']=='AwaitingVisualReview':
                    events=jobs/task_id/'bridge/pinokio-readiness.jsonl'
                    ready=[json.loads(line) for line in events.read_text(encoding='utf-8').splitlines()] if events.exists() else []
                    base=next((item.get('readyUrl','') for item in reversed(ready) if item.get('stage')=='API_READY'),'')
                    parsed=urllib.parse.urlparse(base)
                    if parsed.scheme=='http' and parsed.hostname in {'127.0.0.1','localhost'} and parsed.port:
                        try:
                            req=urllib.request.Request(base.rstrip('/')+'/free',data=b'{"unload_models":true,"free_memory":true}',headers={'Content-Type':'application/json'})
                            with urllib.request.urlopen(req,timeout=30) as response:response.read()
                        except Exception as error:write_json(jobs/task_id/'bridge/memory-release.json',{'error':str(error)})
                service.queue('update',task_id,update={key:result.get(key,'') for key in
                              ('status','pipelineStage','resultPath','bridgeReceipt','error','question')})
                return
        except RuntimeError as error:
            if 'locked by another' not in str(error):raise
            if time.monotonic()>=deadline:raise TimeoutError('GPU tool executor queue timed out')
            time.sleep(1)


def serve(service):
    for line in sys.stdin:
        if len(line)>2_000_000:raise ValueError('MCP message too large')
        request=json.loads(line);identity=request.get('id');method=request.get('method')
        if identity is None:continue
        try:
            if method=='initialize':
                result={'protocolVersion':request['params'].get('protocolVersion','2024-11-05'),
                        'capabilities':{'tools':{}},'serverInfo':{'name':'studio','version':'1.0.0'}}
            elif method=='ping':result={}
            elif method=='tools/list':
                result={'tools':[dict(name=name,description=description,inputSchema=dict(type='object',properties=properties,
                           required=[key for key in properties if key not in {'title','parameters'}],additionalProperties=False))
                                 for name,description,properties in SCHEMAS]}
            elif method=='tools/call':
                params=request['params']
                try:
                    data=service.call(params['name'],params.get('arguments',{}))
                    result={'content':[{'type':'text','text':json.dumps(data,ensure_ascii=True)}]}
                except Exception as error:result={'isError':True,'content':[{'type':'text','text':str(error)}]}
            else:
                print(json.dumps({'jsonrpc':'2.0','id':identity,'error':{'code':-32601,'message':'Method not found'}}),flush=True)
                continue
            print(json.dumps({'jsonrpc':'2.0','id':identity,'result':result}),flush=True)
        except Exception as error:
            print(json.dumps({'jsonrpc':'2.0','id':identity,'error':{'code':-32603,'message':str(error)}}),flush=True)


def verify_tool_reviews(bridge):
    audit=bridge.path/'studio-tool-imports.json'
    if not audit.exists():return
    service=StudioTools(bridge.path/'studio-tools-context.json')
    for imported in read_json(audit):
        task=service.queue('get',imported['task_id'])['task']
        if task['status']!='Completed':
            raise ValueError('Approve tool result '+task['id']+' before approving code that imports its artifacts')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--context',required=True,type=Path)
    parser.add_argument('--execute')
    args=parser.parse_args();service=StudioTools(args.context)
    if args.execute:
        try:execute_child(service,args.execute)
        except Exception as error:
            service.queue('update',args.execute,update=dict(status='NeedsInput',error=str(error),question='Inspect the saved tool receipt; no automatic redispatch.'))
            raise
    else:serve(service)


if __name__=='__main__':main()
