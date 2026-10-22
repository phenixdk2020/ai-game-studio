import copy
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'adapters'))
from pinokio_tools import Pinokio,ToolUnavailable,rank_apps

class PinokioTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)
        self.config=json.loads((ROOT/'config/pinokio-tools.json').read_text())
        self.config['tools']['image_to_3d']['operations']['test']={'api_name':'test','file_inputs':['image'],'artifact_extensions':['.glb'],'defaults':{'steps':5}}
        self.calls=[];self.ready=True
        self.state={'app_id':'Hunyuan3d-2-lowvram.git','ref':'pinokio://localhost:42000/api/hunyuan','ready':True,'source':{'local':True}}
        self.tools=Pinokio(self.config,runner=self.runner,prefix=['pterm'])

    def runner(self,args,**kwargs):
        self.calls.append(args)
        if args[1]=='search':result={'apps':[self.state]}
        else:result={**self.state,'ready':self.ready,'running':False,'default_script':'start.js'}
        return SimpleNamespace(returncode=0,stdout=json.dumps(result),stderr='')

    def server(self,mode='complete'):
        owner=self
        body=json.dumps({'asset':{'version':'2.0'}}).encode();body+=b' '*((-len(body))%4)
        self.glb=struct.pack('<4sII',b'glTF',2,20+len(body))+struct.pack('<II',len(body),0x4e4f534a)+body
        self.posts=[]
        class Handler(BaseHTTPRequestHandler):
            def reply(self,payload,content_type='application/json'):
                payload=payload if isinstance(payload,bytes) else json.dumps(payload).encode()
                self.send_response(200);self.send_header('Content-Type',content_type);self.send_header('Content-Length',str(len(payload)));self.end_headers();self.wfile.write(payload)
            def do_GET(self):
                if self.path=='/gradio_api/info':
                    self.reply({'named_endpoints':{'/test':{'parameters':[{'parameter_name':'image'},{'parameter_name':'steps','parameter_has_default':True,'parameter_default':30}]}}})
                elif self.path.startswith('/gradio_api/call/test/'):
                    url=owner.base+'/gradio_api/file=mesh.glb'
                    if mode=='external':url='http://example.invalid/private.glb'
                    data=[{'value':{'path':'/server/mesh.glb','url':url}}]
                    event='complete'
                    if mode=='error':event='error';data=None
                    self.reply(('event: '+event+'\ndata: '+json.dumps(data)+'\n\n').encode(),'text/event-stream')
                elif self.path.startswith('/gradio_api/file='):
                    self.reply(owner.glb if mode!='bad_glb' else b'bad mesh','model/gltf-binary')
                else:self.send_error(404)
            def do_POST(self):
                body=self.rfile.read(int(self.headers['Content-Length']));owner.posts.append((self.path,body))
                if self.path.endswith('/upload'):self.reply(['/server/upload.png'])
                else:self.reply({'event_id':'event123'})
            def log_message(self,*args):pass
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.base=f'http://127.0.0.1:{server.server_port}'
        self.state['ready_url']=self.base
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        def cleanup():server.shutdown();server.server_close();thread.join(timeout=5)
        self.addCleanup(cleanup)
        image=self.directory/'image.png';image.write_bytes(b'input test image')
        return {'image':{'local_file':str(image)}}

    def test_actual_http_upload_call_sse_download_hash_and_no_duplicate_submission(self):
        parameters=self.server()
        result=self.tools.invoke('image_to_3d','test',parameters,self.state,self.directory/'evidence')
        self.assertEqual(result['artifacts'][0]['sha256'],hashlib.sha256(self.glb).hexdigest())
        call=json.loads(next(body for path,body in self.posts if '/call/' in path))
        self.assertEqual(call['data'][0]['path'],'/server/upload.png');self.assertEqual(call['data'][1],5)
        count=len(self.posts)
        self.assertEqual(self.tools.invoke('image_to_3d','test',parameters,self.state,self.directory/'evidence'),result)
        self.assertEqual(len(self.posts),count)
        Path(parameters['image']['local_file']).write_bytes(b'changed')
        with self.assertRaisesRegex(ToolUnavailable,'inputs or server changed'):
            self.tools.invoke('image_to_3d','test',parameters,self.state,self.directory/'evidence')

    def test_error_stream_cannot_publish_success(self):
        parameters=self.server('error')
        with self.assertRaisesRegex(ToolUnavailable,'generation failed'):
            self.tools.invoke('image_to_3d','test',parameters,self.state,self.directory/'evidence')
        self.assertFalse((self.directory/'evidence/tool-result.json').exists())

    def test_changed_saved_artifact_is_not_replaced_by_another_generation(self):
        parameters=self.server()
        result=self.tools.invoke('image_to_3d','test',parameters,self.state,self.directory/'evidence')
        Path(result['artifacts'][0]['path']).write_bytes(b'changed')
        count=len(self.posts)
        with self.assertRaisesRegex(ToolUnavailable,'Saved artifact'):
            self.tools.invoke('image_to_3d','test',parameters,self.state,self.directory/'evidence')
        self.assertEqual(len(self.posts),count)

    def test_external_artifact_url_rejected(self):
        parameters=self.server('external')
        with self.assertRaisesRegex(ToolUnavailable,'outside'):
            self.tools.invoke('image_to_3d','test',parameters,self.state,self.directory/'evidence')

    def test_invalid_glb_not_published_and_temporary_download_removed(self):
        parameters=self.server('bad_glb')
        with self.assertRaises(ValueError):self.tools.invoke('image_to_3d','test',parameters,self.state,self.directory/'evidence')
        self.assertFalse(list((self.directory/'evidence').glob('artifact-*')))

    def test_only_registered_operation_and_known_parameters_accepted(self):
        parameters=self.server()
        with self.assertRaisesRegex(ToolUnavailable,'not registered'):self.tools.invoke('image_to_3d','unknown',{},self.state,self.directory)
        with self.assertRaisesRegex(ValueError,'Unknown'):self.tools.invoke('image_to_3d','test',{'unknown':1},self.state,self.directory)
        with self.assertRaisesRegex(ValueError,'local_file'):self.tools.invoke('image_to_3d','test',{'image':{'url':'http://example.invalid'}},self.state,self.directory)
        self.assertEqual(self.posts,[])

    def test_ready_app_is_reused_and_probed_without_launch(self):
        with patch('pinokio_tools.subprocess.Popen') as launch:
            result=self.tools.ensure('image_to_3d',self.directory)
            launch.assert_not_called()
        self.assertTrue(result['ready']);self.assertIn('--probe',self.calls[-1])

    def test_offline_requires_approval(self):
        self.ready=False
        with patch('pinokio_tools.subprocess.Popen') as launch,self.assertRaisesRegex(ToolUnavailable,'approve'):
            self.tools.ensure('image_to_3d',self.directory)
        launch.assert_not_called()

    def test_launch_uses_pterm_and_configured_menu_selector(self):
        self.ready=False
        def launch(*args,**kwargs):self.ready=True;return SimpleNamespace(poll=lambda:0,returncode=0)
        with patch('pinokio_tools.subprocess.Popen',side_effect=launch) as process:
            self.tools.ensure('image_to_3d',self.directory,approve=True)
        self.assertIn('start.js?profile=4',process.call_args.args[0]);self.assertEqual(process.call_args.args[0][1],'run')

    def test_remote_localhost_is_not_used_as_caller_url(self):
        state={'source':{'local':False},'ready_url':'http://127.0.0.1:1234','external_ready_urls':['http://192.0.2.1:4567']}
        self.assertEqual(self.tools.base_urls(state),['http://192.0.2.1:4567'])

    def test_runtime_priority_precedes_preferred_offline_app(self):
        rows=[{'app_id':'preferred','ready':False,'score':1000},{'app_id':'online','ready':True,'score':1}]
        self.assertEqual(rank_apps(rows,'preferred')[0]['app_id'],'online')

    def test_search_top_level_preferences_break_same_runtime_ties(self):
        rows=[{'app_id':'a','launch_count_total':1,'score':100},{'app_id':'b','launch_count_total':2,'score':1}]
        self.assertEqual(rank_apps(rows)[0]['app_id'],'b')

    def test_unreachable_control_plane_not_reported_as_missing_pterm(self):
        self.tools.runner=lambda *a,**k:SimpleNamespace(returncode=1,stdout='',stderr='ECONNREFUSED')
        with self.assertRaisesRegex(ToolUnavailable,'unreachable.*installed'):self.tools.discover('image_to_3d')

if __name__=='__main__':unittest.main()
