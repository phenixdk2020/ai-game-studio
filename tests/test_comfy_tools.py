from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import threading
import unittest
import zlib
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'adapters'))
from pinokio_tools import Pinokio,ToolUnavailable
from comfy_tools import CLASSES,workflow,validate_png

def png():
    def chunk(kind,data):return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1,1,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(b'\0\x20\x40\x80'))+chunk(b'IEND',b'')

class ComfyTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.path=Path(self.temp.name)
        self.config=json.loads((ROOT/'config/pinokio-tools.json').read_text())
        self.tools=Pinokio(self.config,prefix=['pterm']);self.posts=[];self.mode='success';self.prompt_id='';self.checkpoints=['model.safetensors']
        self.nodes={name:{'input':{'required':{}}} for name in CLASSES}
        self.nodes['KSampler']['input']['required']={'sampler_name':[['euler']],'scheduler':[['normal']]}
        owner=self
        class Handler(BaseHTTPRequestHandler):
            def reply(self,value,ctype='application/json'):
                data=value if isinstance(value,bytes) else json.dumps(value).encode()
                self.send_response(200);self.send_header('Content-Type',ctype);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            def do_GET(self):
                if self.path=='/system_stats':self.reply({'system':{'comfyui_version':'test'}})
                elif self.path.startswith('/object_info/'):
                    name=self.path.rsplit('/',1)[-1]
                    owner.nodes['CheckpointLoaderSimple']['input']['required']['ckpt_name']=[owner.checkpoints]
                    self.reply({name:owner.nodes[name]})
                elif self.path.startswith('/history/'):
                    if owner.mode=='pending':self.reply({});return
                    status={'status_str':'error' if owner.mode=='error' else 'success','completed':owner.mode!='error'}
                    outputs={'7':{'images':[{'filename':'result.png','subfolder':'','type':'output'}]}}
                    if owner.mode=='no_image':outputs={}
                    self.reply({owner.prompt_id:{'status':status,'outputs':outputs}})
                elif self.path.startswith('/view?'):self.reply(png() if owner.mode!='bad_png' else b'not png','image/png')
                else:self.send_error(404)
            def do_POST(self):
                value=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                owner.posts.append(value);owner.prompt_id=value['prompt_id']
                self.reply({'prompt_id':owner.prompt_id,'node_errors':{}})
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        self.addCleanup(lambda:(server.shutdown(),server.server_close(),thread.join(timeout=5)))
        self.state={'app_id':'comfy.git','source':{'local':True},'ready_url':f'http://127.0.0.1:{server.server_port}'}

    def invoke(self,**parameters):
        return self.tools.invoke('image_generation','generate_image',{'prompt':'A blue prop',**parameters},self.state,self.path)

    def test_real_http_workflow_history_png_and_reuse(self):
        result=self.invoke(steps=2)
        self.assertEqual(len(self.posts),1);self.assertEqual(self.posts[0]['prompt']['5']['inputs']['steps'],2)
        self.assertEqual(Path(result['artifacts'][0]['path']).read_bytes(),png())
        self.assertEqual(self.invoke(steps=2),result);self.assertEqual(len(self.posts),1)
        self.assertTrue((self.path/'workflow.json').exists())
        self.assertEqual(json.loads((self.path/'tool-progress.json').read_text())['status'],'AwaitingVisualReview')

    def test_changed_task_does_not_submit_twice(self):
        self.invoke()
        with self.assertRaisesRegex(ToolUnavailable,'inputs/server changed'):self.invoke(seed=42)
        self.assertEqual(len(self.posts),1)

    def test_existing_job_does_not_require_new_model_selection(self):
        result=self.invoke()
        self.checkpoints=['different.safetensors','second.safetensors']
        self.assertEqual(self.invoke(),result);self.assertEqual(len(self.posts),1)

    def test_execution_error_is_recorded(self):
        self.mode='error'
        with self.assertRaisesRegex(ToolUnavailable,'execution failed'):self.invoke()
        self.assertTrue((self.path/'tool-error.json').exists());self.assertFalse((self.path/'tool-result.json').exists())

    def test_missing_image_not_treated_as_success(self):
        self.mode='no_image'
        with self.assertRaisesRegex(ToolUnavailable,'without.*image'):self.invoke()

    def test_invalid_png_not_published(self):
        self.mode='bad_png'
        with self.assertRaisesRegex(ValueError,'PNG'):self.invoke()
        self.assertFalse((self.path/'artifact-0.png').exists())

    def test_unknown_workflow_parameters_and_invalid_dimensions_rejected(self):
        for values in ({'workflow':{}},{'width':65},{'steps':True},{'cfg':float('nan')},{'checkpoint':'not-installed'}):
            with self.subTest(values=values),self.assertRaises(ValueError):self.invoke(**values)
        self.assertEqual(self.posts,[])

    def test_multiple_checkpoints_require_selection(self):
        self.checkpoints=['a.safetensors','b.safetensors']
        with self.assertRaisesRegex(ToolUnavailable,'explicitly'):self.invoke()
        self.assertEqual(self.posts,[])
        self.assertEqual(self.invoke(checkpoint='b.safetensors')['parameters']['checkpoint'],'b.safetensors')

    def test_timeout_preserves_prompt_and_does_not_redispatch(self):
        self.mode='pending';self.config['request_timeout']=3;clock=[0]
        self.tools.clock=lambda:clock[0];self.tools.sleep=lambda seconds:clock.__setitem__(0,clock[0]+seconds)
        for _ in range(2):
            with self.assertRaisesRegex(ToolUnavailable,'pending'):self.invoke()
        self.assertEqual(len(self.posts),1)
        self.assertEqual(json.loads((self.path/'tool-progress.json').read_text())['status'],'WaitingForResult')

    def test_interrupted_dispatch_is_not_automatically_sent_again(self):
        self.invoke();(self.path/'tool-result.json').unlink()
        receipt=json.loads((self.path/'tool-call.json').read_text());receipt['status']='Dispatching';(self.path/'tool-call.json').write_text(json.dumps(receipt))
        with self.assertRaisesRegex(ToolUnavailable,'Interrupted'):self.invoke()
        self.assertEqual(len(self.posts),1)

    def test_png_checksum_damage_is_detected(self):
        path=self.path/'image.png';path.write_bytes(png());validate_png(path)
        value=bytearray(png());value[20]^=1;path.write_bytes(value)
        with self.assertRaisesRegex(ValueError,'checksum'):validate_png(path)

    @unittest.skipUnless(shutil.which('pwsh') or shutil.which('powershell.exe'),'PowerShell required')
    def test_cli_worker_image_result_and_approval_round_trip(self):
        root=self.path/'studio';root.mkdir()
        for directory in ('adapters','config','agents'):shutil.copytree(ROOT/directory,root/directory,ignore=shutil.ignore_patterns('__pycache__'))
        app={**self.state,'ready':True,'running':True}
        launcher=root/'test-pterm.ps1'
        launcher.write_text("$app='"+json.dumps(app)+"'|ConvertFrom-Json;if($args[0] -eq 'search'){@{apps=@($app)}|ConvertTo-Json -Depth 10}else{$app|ConvertTo-Json -Depth 10}",encoding='utf-8-sig')
        config=json.loads((root/'config/pinokio-tools.json').read_text());config['pterm']=str(launcher)
        (root/'config/pinokio-tools.json').write_text(json.dumps(config))
        host=shutil.which('pwsh') or shutil.which('powershell.exe')
        request={'action':'add','root':str(root),'title':'Image test','description':'Blue prop','backend':'pinokio','role':'art_world','kind':'task','attachments':[],'dependencies':[],'projectPath':'','toolCapability':'image_generation','toolOperation':'generate_image','toolParameters':{'prompt':'Blue prop','steps':2},'toolAppId':'comfy.git'}
        file=root/'request.json';file.write_text(json.dumps(request))
        def command(args):
            result=subprocess.run([host,'-NoProfile',*args],capture_output=True,text=True,errors='replace',timeout=45)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        command(['-File',str(ROOT/'tools/studio.ps1'),'-RequestFile',str(file)])
        command(['-File',str(ROOT/'tools/project-manager-worker.ps1'),'-Root',str(root),'-Once','-EnableSpecialists','-Python',sys.executable])
        task=json.loads((root/'tasks/queue.gui.json').read_text())[0]
        self.assertEqual(task['status'],'AwaitingVisualReview',task)
        artifact=json.loads(Path(task['resultPath']).read_text())['artifacts'][0]
        self.assertEqual(Path(artifact['path']).read_bytes(),png());self.assertEqual(len(self.posts),1)
        file.write_text(json.dumps({'action':'approve','root':str(root),'id':task['id']}))
        command(['-File',str(ROOT/'tools/studio.ps1'),'-RequestFile',str(file)])
        self.assertEqual(json.loads((root/'tasks/queue.gui.json').read_text())[0]['status'],'Completed')

if __name__=='__main__':unittest.main()
