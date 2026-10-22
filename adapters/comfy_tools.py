"""Fixed, inspected ComfyUI text-to-image workflow through its public HTTP API."""
import hashlib
import json
from pathlib import Path
import re
import struct
import time
import urllib.parse
import urllib.request
import urllib.error
import uuid
import zlib

from pinokio_tools import ToolUnavailable,read_json

CLASSES=('CheckpointLoaderSimple','CLIPTextEncode','EmptyLatentImage','KSampler','VAEDecode','SaveImage')

def request_json(base,path,payload=None,timeout=10):
    data=None if payload is None else json.dumps(payload).encode()
    request=urllib.request.Request(base+path,data=data,headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=timeout) as response:return json.load(response)
    except urllib.error.HTTPError as error:
        detail=error.read(2048).decode('utf-8',errors='replace')
        raise ToolUnavailable(f'ComfyUI API rejected request ({error.code}): '+detail) from error

def inspect_comfy(base):
    stats=request_json(base,'/system_stats')
    if not isinstance(stats,dict) or not isinstance(stats.get('system'),dict):raise ToolUnavailable('Not a ComfyUI system API')
    nodes={}
    for name in CLASSES:
        value=request_json(base,'/object_info/'+name)
        if name not in value:raise ToolUnavailable('Missing required ComfyUI node '+name)
        nodes[name]=value[name]
    return {'protocol':'comfyui','base_url':base,'api_prefix':'','info':{'nodes':nodes,'system':stats['system']}}

def validate_png(path):
    content=Path(path).read_bytes()
    if content[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError('Invalid PNG signature')
    offset=8;first=True;data=False;ended=False
    while offset<len(content):
        if offset+12>len(content):raise ValueError('Truncated PNG')
        length,kind=struct.unpack('>I4s',content[offset:offset+8]);end=offset+12+length
        if end>len(content):raise ValueError('Truncated PNG chunk')
        value=content[offset+8:offset+8+length]
        crc=struct.unpack('>I',content[offset+8+length:end])[0]
        if zlib.crc32(kind+value)&0xffffffff!=crc:raise ValueError('PNG checksum mismatch')
        if first:
            if kind!=b'IHDR' or length!=13:raise ValueError('Invalid PNG header')
            width,height=struct.unpack('>II',value[:8])
            if not 1<=width<=8192 or not 1<=height<=8192:raise ValueError('Invalid PNG dimensions')
        first=False;data=data or kind==b'IDAT'
        if kind==b'IEND':
            if length or end!=len(content):raise ValueError('Invalid PNG ending')
            ended=True;break
        offset=end
    if not data or not ended:raise ValueError('Incomplete PNG')

def workflow(parameters,nodes):
    allowed={'prompt','negative_prompt','checkpoint','width','height','steps','seed','cfg'}
    if set(parameters)-allowed:raise ValueError('Unknown image parameters: '+str(set(parameters)-allowed))
    if not isinstance(parameters.get('prompt'),str) or not 1<=len(parameters['prompt'].strip())<=8000:raise ValueError('A nonempty image prompt is required')
    for key,minimum,maximum in (('width',64,2048),('height',64,2048),('steps',1,100),('seed',0,2**63-1)):
        value=parameters[key]
        if type(value)!=int or not minimum<=value<=maximum:raise ValueError('Invalid '+key)
    if parameters['width']%64 or parameters['height']%64:raise ValueError('Image dimensions must be multiples of 64')
    if type(parameters['cfg']) not in (int,float) or not 0<=parameters['cfg']<=30:raise ValueError('Invalid cfg')
    if not isinstance(parameters['negative_prompt'],str) or len(parameters['negative_prompt'])>8000:raise ValueError('Invalid negative prompt')
    checkpoints=nodes['CheckpointLoaderSimple']['input']['required']['ckpt_name'][0]
    checkpoint=parameters.get('checkpoint')
    if not checkpoint:
        if len(checkpoints)!=1:raise ToolUnavailable('Select an installed checkpoint explicitly: '+', '.join(checkpoints[:30]))
        checkpoint=checkpoints[0]
    if checkpoint not in checkpoints:raise ValueError('Checkpoint is not installed')
    sampler=nodes['KSampler']['input']['required']['sampler_name'][0]
    scheduler=nodes['KSampler']['input']['required']['scheduler'][0]
    if 'euler' not in sampler or 'normal' not in scheduler:raise ToolUnavailable('Required sampling settings are unavailable')
    return {
        '1':{'class_type':'CheckpointLoaderSimple','inputs':{'ckpt_name':checkpoint}},
        '2':{'class_type':'CLIPTextEncode','inputs':{'text':parameters['prompt'],'clip':['1',1]}},
        '3':{'class_type':'CLIPTextEncode','inputs':{'text':parameters['negative_prompt'],'clip':['1',1]}},
        '4':{'class_type':'EmptyLatentImage','inputs':{'width':parameters['width'],'height':parameters['height'],'batch_size':1}},
        '5':{'class_type':'KSampler','inputs':{'model':['1',0],'positive':['2',0],'negative':['3',0],'latent_image':['4',0],'seed':parameters['seed'],'steps':parameters['steps'],'cfg':parameters['cfg'],'sampler_name':'euler','scheduler':'normal','denoise':1.0}},
        '6':{'class_type':'VAEDecode','inputs':{'samples':['5',0],'vae':['1',2]}},
        '7':{'class_type':'SaveImage','inputs':{'images':['6',0],'filename_prefix':'AIStudio_Tool'}}}

def generate_image(tools,capability,operation,parameters,state,evidence,config):
    if not isinstance(parameters,dict):raise ValueError('Tool parameters must be an object')
    allowed=tools.config['tools'][capability].get('supported_apps',[])
    if state.get('app_id') not in allowed:raise ToolUnavailable('This operation is not registered for the selected app')
    api=tools.inspect(state)
    if api.get('protocol')!='comfyui':raise ToolUnavailable('Selected app does not expose the required ComfyUI API')
    parameters={**config['defaults'],**parameters};base=api['base_url']
    signature=hashlib.sha256(json.dumps({'parameters':parameters,'base':base},sort_keys=True).encode()).hexdigest()
    ticket_path=evidence/'tool-call.json';result_path=evidence/'tool-result.json'
    if ticket_path.exists():
        ticket=read_json(ticket_path)
        if ticket.get('signature')!=signature:raise ToolUnavailable('Image inputs/server changed; create a new task')
        if result_path.exists():
            result=read_json(result_path)
            for item in result['artifacts']:
                path=Path(item['path'])
                if path.parent.resolve()!=evidence.resolve() or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=item['sha256']:raise ToolUnavailable('Saved image artifact is missing or changed')
            return result
        if ticket.get('status')!='Submitted':raise ToolUnavailable('Interrupted image dispatch; reconcile the recorded prompt ID before retrying')
    else:
        graph=workflow(parameters,api['info']['nodes'])
        ticket={'signature':signature,'prompt_id':str(uuid.uuid4()),'status':'Dispatching'}
        ticket_path.write_text(json.dumps(ticket))
        (evidence/'workflow.json').write_text(json.dumps(graph,indent=2))
        submitted=request_json(base,'/prompt',{'prompt':graph,'prompt_id':ticket['prompt_id'],'client_id':str(uuid.uuid4())},timeout=tools.config['command_timeout'])
        if submitted.get('node_errors'):raise ToolUnavailable('ComfyUI workflow validation failed: '+json.dumps(submitted['node_errors']))
        prompt_id=submitted.get('prompt_id','')
        if not re.fullmatch(r'[a-f0-9-]{36}',prompt_id):raise ToolUnavailable('Invalid ComfyUI prompt ID')
        ticket.update(prompt_id=prompt_id,status='Submitted');ticket_path.write_text(json.dumps(ticket))
    deadline=tools.clock()+tools.config['request_timeout']
    started=tools.clock()
    while tools.clock()<deadline:
        from asset_pipeline import write_json
        write_json(evidence/'tool-progress.json',{'status':'WaitingForResult','prompt_id':ticket['prompt_id'],'elapsed_seconds':round(tools.clock()-started,1),'message':'Job submitted. Waiting for ComfyUI model loading, execution and image output.'})
        history=request_json(base,'/history/'+ticket['prompt_id'])
        entry=history.get(ticket['prompt_id'])
        if entry:
            status=entry.get('status',{})
            if status.get('status_str')=='error':
                (evidence/'tool-error.json').write_text(json.dumps(entry,indent=2))
                raise ToolUnavailable('ComfyUI execution failed; inspect tool-error.json')
            if status.get('completed'):
                images=entry.get('outputs',{}).get('7',{}).get('images',[])
                if not images:raise ToolUnavailable('ComfyUI completed without the registered image output')
                files=[]
                for image in images:
                    if image.get('type')!='output' or not str(image.get('filename','')).lower().endswith('.png'):raise ToolUnavailable('Unexpected ComfyUI output type')
                    query=urllib.parse.urlencode({key:image.get(key,'') for key in ('filename','subfolder','type')})
                    files.append({'path':image['filename'],'url':base+'/view?'+query})
                saved_graph=read_json(evidence/'workflow.json')
                result={'schemaVersion':1,'capability':capability,'operation':operation,'app_id':state['app_id'],'ref':state.get('ref'),'prompt_id':ticket['prompt_id'],'output':images,'parameters':parameters,'checkpoint':saved_graph['1']['inputs']['ckpt_name']}
                result['artifacts']=tools.download_artifacts(files,api,evidence,['.png'])
                result_path.write_text(json.dumps(result,indent=2))
                write_json(evidence/'tool-progress.json',{'status':'AwaitingVisualReview','prompt_id':ticket['prompt_id'],'message':'Image downloaded and PNG checks passed. Review the result.'})
                return result
        tools.sleep(2)
    raise ToolUnavailable('ComfyUI result is still pending; preserve the recorded prompt ID, no automatic redispatch')
