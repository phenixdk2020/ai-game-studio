"""Pinokio tools: discover and launch via pterm, call inspected Gradio APIs.

No direct app Python launch, installs, registry downloads, updates or app shutdown.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import mimetypes

ROOT=Path(__file__).resolve().parents[1]

class ToolUnavailable(RuntimeError): pass

def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def resolve_pterm(config, home=None):
    settings_path=Path(home or Path.home())/'.pinokio/config.json'
    settings=read_json(settings_path) if settings_path.exists() else {}
    candidates=[]
    if config.get('pterm'): candidates.append(config['pterm'])
    if settings.get('home'):
        base=Path(settings['home'])
        candidates.extend(str(base/path) for path in ('bin/npm/pterm','bin/npm/bin/pterm','bin/pterm'))
    found=shutil.which('pterm')
    if found:candidates.append(found)
    for value in candidates:
        path=Path(value)
        choices=[path]
        if os.name=='nt':
            choices=[path.with_suffix('.ps1'),path.with_suffix('.cmd'),path] if not path.suffix else [path]
        for choice in choices:
            if not choice.is_file():continue
            if choice.suffix.lower()=='.cmd' and choice.with_suffix('.ps1').exists():choice=choice.with_suffix('.ps1')
            if choice.suffix.lower()=='.ps1':
                host=shutil.which('pwsh') or shutil.which('powershell.exe')
                if not host:continue
                return [host,'-NoProfile','-ExecutionPolicy','Bypass','-File',str(choice)]
            return [str(choice)]
    # The control-plane lookup is discovery only, never a substitute lifecycle API.
    try:
        with urllib.request.urlopen('http://127.0.0.1:42000/pinokio/path/pterm',timeout=2) as response:
            value=json.load(response)
        candidate=value.get('path') if isinstance(value,dict) else value
        if isinstance(candidate,str) and Path(candidate).is_file():
            return resolve_pterm({**config,'pterm':candidate},home)
    except (OSError,ValueError):pass
    raise ToolUnavailable('pterm could not be resolved from Pinokio home, control-plane lookup or PATH')

def rank_apps(apps, preferred=None):
    def key(app):
        preference=app.get('preference') or {}
        return (2 if app.get('ready') else 1 if app.get('running') else 0,
                app.get('app_id')==preferred, bool(app.get('starred',preference.get('starred'))),
                app.get('matched_terms_count') or 0,app.get('launch_count_total',preference.get('launch_count_total',0)) or 0,
                str(app.get('last_launch_at',preference.get('last_launch_at')) or ''),app.get('score') or 0)
    return sorted(apps,key=key,reverse=True)

class Pinokio:
    def __init__(self,config,runner=subprocess.run,prefix=None,clock=time.monotonic,sleep=time.sleep):
        self.config=config;self.runner=runner;self.prefix=prefix;self.clock=clock;self.sleep=sleep

    def command(self,args):
        prefix=self.prefix or resolve_pterm(self.config)
        try:
            result=self.runner(prefix+args,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=self.config['command_timeout'])
        except subprocess.TimeoutExpired as error:raise ToolUnavailable('Pinokio control command timed out') from error
        if result.returncode:
            detail=result.stderr or result.stdout
            if 'ECONNREFUSED' in detail:raise ToolUnavailable('Pinokio control plane is unreachable (connection refused); pterm is installed')
            raise ToolUnavailable('pterm failed: '+detail[:2000])
        try:return json.loads(result.stdout)
        except ValueError as error:raise ToolUnavailable('pterm returned no valid JSON') from error

    def discover(self,capability):
        tool=self.config['tools'][capability]
        query=tool['query'];minimum='2' if len(query.split())>=3 else '1'
        response=self.command(['search',query,'--mode','balanced','--min-match',minimum,'--limit','8'])
        def compatible(items):
            allowed=tool.get('supported_apps')
            return [app for app in items if not allowed or app.get('app_id') in allowed]
        apps=compatible(response.get('apps',[]))
        if not apps:
            response=self.command(['search',query,'--mode','broad','--limit','8']);apps=compatible(response.get('apps',[]))
        if not apps:raise ToolUnavailable('No installed app found for '+capability+'; no installation was attempted')
        return rank_apps(apps,tool.get('preferred_app'))

    def status(self,target,probe=False):
        return self.command(['status',target]+(['--probe','--timeout=3000'] if probe else []))

    def ensure(self,capability,evidence,app_id=None,approve=False):
        apps=self.discover(capability)
        if app_id:
            apps=[app for app in apps if app.get('app_id')==app_id or app.get('ref')==app_id]
            if not apps:raise ToolUnavailable('Requested app was not found by capability search')
        elif len(apps)>1:
            first,second=apps[:2]
            if (bool(first.get('ready')),bool(first.get('running'))) == (bool(second.get('ready')),bool(second.get('running'))) and first.get('app_id')!=self.config['tools'][capability].get('preferred_app'):
                raise ToolUnavailable('Several apps match; select an explicit app_id: '+', '.join(str(app.get('app_id')) for app in apps[:3]))
        selected=apps[0];target=selected.get('ref') or selected.get('app_id')
        state=self.status(target)
        process=None
        if not state.get('ready'):
            if not approve:raise ToolUnavailable('App is offline; approve Pinokio tool execution to launch it')
            if not state.get('running'):
                selectors=self.config['tools'][capability].get('selectors',[])
                if not selectors and not state.get('default_target') and not state.get('default_script'):
                    raise ToolUnavailable('No unambiguous launch selector; inspect the app menu and configure one')
                args=['run',target]
                for selector in selectors:args+=['--default',selector]
                evidence=Path(evidence);evidence.mkdir(parents=True,exist_ok=True)
                with (evidence/'pinokio-launch.txt').open('wb') as stream:
                    process=subprocess.Popen((self.prefix or resolve_pterm(self.config))+args,stdout=stream,stderr=subprocess.STDOUT)
            deadline=self.clock()+self.config['tools'][capability].get('startup_timeout',self.config['startup_timeout'])
            while self.clock()<deadline:
                state=self.status(target)
                if state.get('ready'):break
                if process and process.poll() is not None and process.returncode:
                    raise ToolUnavailable('Pinokio launch failed; '+json.dumps(self.command(['logs',target,'--tail','100'])))
                self.sleep(2)
            else:raise ToolUnavailable('Pinokio app did not become ready; '+json.dumps(self.command(['logs',target,'--tail','100'])))
        state=self.status(target,probe=True)
        if not state.get('ready'):raise ToolUnavailable('Pinokio readiness probe failed')
        return state

    def base_urls(self,state):
        remote=(state.get('source') or {}).get('local') is False
        values=[] if remote else [state.get('ready_url')]
        values+=state.get('external_ready_urls') or []
        return [value.rstrip('/') for value in values if isinstance(value,str) and urllib.parse.urlparse(value).scheme in ('http','https')]

    def inspect(self,state):
        failures=[]
        for base in self.base_urls(state):
            for prefix in ('/gradio_api',''):
                try:
                    with urllib.request.urlopen(base+prefix+'/info',timeout=10) as response:info=json.load(response)
                    if not isinstance(info.get('named_endpoints'),dict):continue
                    return {'base_url':base,'api_prefix':prefix,'info':info}
                except (OSError,ValueError) as error:failures.append(str(error))
            try:
                from comfy_tools import inspect_comfy
                return inspect_comfy(base)
            except (OSError,ValueError,ToolUnavailable) as error:failures.append(str(error))
        raise ToolUnavailable('No supported documented app API could be reached: '+'; '.join(failures)[-1000:])

    def invoke(self,capability,operation,parameters,state,evidence):
        from asset_pipeline import task_lock
        evidence=Path(evidence);evidence.mkdir(parents=True,exist_ok=True)
        with task_lock(evidence):
            return self._invoke(capability,operation,parameters,state,evidence)

    def _invoke(self,capability,operation,parameters,state,evidence):
        operation_config=self.config['tools'][capability].get('operations',{}).get(operation)
        if not operation_config:raise ToolUnavailable('Operation is not registered; inspect the app API first')
        if operation_config.get('protocol')=='comfyui':
            from comfy_tools import generate_image
            return generate_image(self,capability,operation,parameters,state,Path(evidence),operation_config)
        api=self.inspect(state);name=operation_config['api_name']
        endpoint=api['info']['named_endpoints'].get('/'+name.lstrip('/'))
        if not endpoint:raise ToolUnavailable('Registered API operation no longer exists; refresh the app contract')
        if not isinstance(parameters,dict):raise ValueError('Tool parameters must be an object')
        evidence=Path(evidence);evidence.mkdir(parents=True,exist_ok=True)
        original={**operation_config.get('defaults',{}),**parameters}
        input_hashes={}
        for key in operation_config.get('file_inputs',[]):
            value=original.get(key)
            if isinstance(value,dict) and set(value)=={'local_file'}:
                path=Path(value['local_file'])
                if not path.is_file() or path.stat().st_size>32*1024*1024:raise ValueError('Invalid input file')
                input_hashes[key]=hashlib.sha256(path.read_bytes()).hexdigest()
        signature=hashlib.sha256(json.dumps({'capability':capability,'operation':operation,'parameters':original,'inputs':input_hashes,'base':api['base_url']},sort_keys=True).encode()).hexdigest()
        ticket_path=evidence/'tool-call.json'
        if ticket_path.exists():
            previous=read_json(ticket_path)
            if previous.get('signature')!=signature:raise ToolUnavailable('Tool inputs or server changed; use a new task to preserve the existing call')
            if (evidence/'tool-result.json').exists():
                saved=read_json(evidence/'tool-result.json')
                for item in saved.get('artifacts',[]):
                    path=Path(item['path'])
                    if path.parent.resolve()!=evidence.resolve() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:
                        raise ToolUnavailable('Saved artifact is missing or changed; no new generation was dispatched')
                return saved
            if not previous.get('event_id'):raise ToolUnavailable('Interrupted tool dispatch; reconcile app logs before creating another generation')
        parameters=original
        schema=endpoint['parameters'];names=[item['parameter_name'] for item in schema]
        if set(parameters)-set(names):raise ValueError('Unknown API parameters: '+str(set(parameters)-set(names)))
        data=[]
        for item in schema:
            key=item['parameter_name']
            if key in parameters:
                value=parameters[key]
                if key in operation_config.get('file_inputs',[]):
                    if not isinstance(value,dict) or set(value)!={'local_file'}:raise ValueError(key+' requires {"local_file":"path"}')
                    value=self.upload(api,Path(value['local_file']))
                elif isinstance(value,dict) and ('path' in value or 'url' in value):raise ValueError('Unregistered file/URL input')
                data.append(value)
            elif item.get('parameter_has_default'):data.append(item.get('parameter_default'))
            else:raise ValueError('Missing API parameter: '+key)
        base=api['base_url']+api['api_prefix']
        if ticket_path.exists():ticket=read_json(ticket_path)
        else:
            ticket_path.write_text(json.dumps({'signature':signature,'status':'Dispatching'}))
            request=urllib.request.Request(base+'/call/'+name.lstrip('/'),data=json.dumps({'data':data}).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=self.config['request_timeout']) as response:ticket=json.load(response)
            ticket_path.write_text(json.dumps({**ticket,'signature':signature,'status':'Submitted'}))
        event_id=ticket['event_id']
        if not isinstance(event_id,str) or not event_id.isalnum():raise ValueError('Invalid Gradio event id')
        event='';buffer=[];deadline=self.clock()+self.config['request_timeout']
        with urllib.request.urlopen(base+'/call/'+name.lstrip('/')+'/'+event_id,timeout=self.config['request_timeout']) as response:
            for raw in response:
                if self.clock()>deadline:raise ToolUnavailable('Tool result wait exceeded its deadline; preserve event receipt before retrying')
                line=raw.decode('utf-8').rstrip('\r\n')
                if line.startswith('event:'):event=line[6:].strip()
                elif line.startswith('data:'):buffer.append(line[5:].strip())
                elif not line and buffer:
                    payload=json.loads('\n'.join(buffer));buffer=[]
                    if event=='error':
                        detail={'error':payload,'event_id':event_id}
                        try:detail['app_logs']=self.command(['logs',state.get('ref') or state['app_id'],'--tail','60'])
                        except ToolUnavailable as error:detail['log_error']=str(error)
                        (evidence/'tool-error.json').write_text(json.dumps(detail,indent=2),encoding='utf-8')
                        raise ToolUnavailable('App generation failed; inspect tool-error.json and Pinokio logs. Event: '+event_id)
                    if event=='complete':
                        evidence=Path(evidence);evidence.mkdir(parents=True,exist_ok=True)
                        result={'schemaVersion':1,'capability':capability,'operation':operation,'app_id':state['app_id'],'ref':state.get('ref'),'event_id':event_id,'output':payload}
                        result['artifacts']=self.download_artifacts(payload,api,evidence,operation_config.get('artifact_extensions',[]))
                        (evidence/'tool-result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
                        return result
        raise ToolUnavailable('App stream ended without completion')

    def upload(self,api,path):
        if not path.is_file() or path.stat().st_size>32*1024*1024:raise ValueError('Input file is missing or larger than 32 MiB')
        boundary='studio'+uuid.uuid4().hex
        filename=path.name.replace('"','_').replace('\r','_').replace('\n','_')
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="{filename}"\r\nContent-Type: {mimetypes.guess_type(filename)[0] or "application/octet-stream"}\r\n\r\n').encode()+path.read_bytes()+f'\r\n--{boundary}--\r\n'.encode()
        request=urllib.request.Request(api['base_url']+api['api_prefix']+'/upload',data=body,headers={'Content-Type':'multipart/form-data; boundary='+boundary})
        with urllib.request.urlopen(request,timeout=30) as response:paths=json.load(response)
        if not isinstance(paths,list) or len(paths)!=1 or not isinstance(paths[0],str):raise ToolUnavailable('Invalid Gradio upload response')
        return {'path':paths[0],'orig_name':filename,'meta':{'_type':'gradio.FileData'}}

    def download_artifacts(self,payload,api,evidence,extensions):
        files=[]
        def visit(value):
            if isinstance(value,dict):
                if isinstance(value.get('path'),str) and Path(value['path']).suffix.lower() in extensions:files.append(value)
                else:
                    for child in value.values():visit(child)
            elif isinstance(value,list):
                for child in value:visit(child)
        visit(payload)
        artifacts=[];seen=set()
        for file in files:
            url=file.get('url') or api['base_url']+api['api_prefix']+'/file='+urllib.parse.quote(file['path'],safe='/:')
            url=urllib.parse.urljoin(api['base_url']+'/',url)
            if urllib.parse.urlparse(url).netloc!=urllib.parse.urlparse(api['base_url']).netloc or urllib.parse.urlparse(url).scheme!=urllib.parse.urlparse(api['base_url']).scheme:
                raise ToolUnavailable('App returned an artifact outside its own server')
            if url in seen:continue
            seen.add(url)
            target=Path(evidence)/('artifact-'+str(len(artifacts))+Path(file['path']).suffix.lower())
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self,*args,**kwargs):raise ToolUnavailable('Artifact redirects are not accepted')
            temporary=target.with_suffix(target.suffix+'.tmp')
            try:
                with urllib.request.build_opener(NoRedirect).open(url,timeout=self.config['request_timeout']) as response,temporary.open('wb') as output:
                    total=0
                    while True:
                        chunk=response.read(1024*1024)
                        if not chunk:break
                        total+=len(chunk)
                        if total>256*1024*1024:raise ToolUnavailable('Artifact exceeds 256 MiB')
                        output.write(chunk)
                if target.suffix=='.glb':
                    from asset_pipeline import validate_glb
                    validate_glb(temporary)
                elif target.suffix=='.png':
                    from comfy_tools import validate_png
                    validate_png(temporary)
                temporary.replace(target)
            finally:temporary.unlink(missing_ok=True)
            artifacts.append({'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'bytes':target.stat().st_size})
        if extensions and not artifacts:raise ToolUnavailable('App completed without the required artifact')
        return artifacts

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,default=ROOT/'config/pinokio-tools.json')
    parser.add_argument('--evidence',type=Path,default=ROOT/'data/pinokio-evidence')
    parser.add_argument('action',choices=('catalog','discover','ensure','inspect','invoke'))
    parser.add_argument('capability',nargs='?');parser.add_argument('--app-id');parser.add_argument('--approve-launch',action='store_true')
    parser.add_argument('--operation');parser.add_argument('--parameters-json',default='{}');parser.add_argument('--approve-call',action='store_true')
    args=parser.parse_args()
    try:
        tools=Pinokio(read_json(args.config))
        if args.action=='catalog':
            result={'tools':[{ 'capability':key,'roles':value['roles'],'operations':['inspect']+list(value.get('operations',{})),'apps':tools.discover(key)} for key,value in tools.config['tools'].items()]}
        elif args.action=='discover':result=tools.discover(args.capability)
        else:
            if args.action=='invoke' and not args.approve_call:raise ValueError('Tool invocation requires --approve-call')
            if args.action=='invoke' and args.operation not in tools.config['tools'][args.capability].get('operations',{}):raise ValueError('Tool operation is not registered')
            state=tools.ensure(args.capability,args.evidence,args.app_id,args.approve_launch)
            if args.action=='invoke':
                result=tools.invoke(args.capability,args.operation,json.loads(args.parameters_json),state,args.evidence)
            else:result=state if args.action=='ensure' else tools.inspect(state)
        print(json.dumps(result));return 0
    except Exception as error:
        print(json.dumps({'status':'NeedsInput','error':str(error)}));return 1

if __name__=='__main__':sys.exit(main())
