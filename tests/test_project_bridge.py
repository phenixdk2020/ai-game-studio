"""Provider contracts use fake external CLIs; no paid coding session is started."""
import copy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'adapters'))
from project_bridge import Bridge, normalize_plan, validate

SHA='a'*40
URL='https://github.com/example/studio/pull/7'

class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config=json.loads((ROOT/'config/orchestrator.json').read_text())
        self.config.update(jobs_root=self.temp.name,repository='example/studio')
        self.task=dict(id='TASK-TEST',title='Implement menu',description='Add menu code',backend='copilot-github',role='gameplay')
        self.calls=[];self.session_state='completed';self.remote_sha=SHA;self.fail_validation=False;self.changed_path='app.py';self.pr_state='MERGED'

    def runner(self,args,**kwargs):
        self.calls.append(args)
        output='';code=0
        if 'clone' in args: Path(args[-1]).mkdir()
        elif args[1:3]==['agent-task','create']: output=URL
        elif args[1:3]==['agent-task','view']: output=json.dumps(dict(id='session-7',state=self.session_state,pullRequestUrl=URL))
        elif args[1:3]==['pr','view']: output=json.dumps(dict(url=URL,headRefOid=self.remote_sha,baseRefName='main',isCrossRepository=False,state=self.pr_state))
        elif args[1:3]==['pr','create']: output=URL
        elif 'rev-parse' in args: output=SHA
        elif '--name-only' in args: output=self.changed_path
        elif args[1:3]==['status','--porcelain']: output=' M app.py'
        elif 'unittest' in args and self.fail_validation: code=1
        return SimpleNamespace(stdout=output,stderr='test failure' if code else '',returncode=code)

    def bridge(self,**kwargs):
        bridge=Bridge(self.task,self.config,runner=self.runner,**kwargs)
        bridge.tool=lambda name: name
        return bridge

    def dispatch_and_validate(self):
        bridge=self.bridge()
        self.assertEqual(bridge.advance(True)['status'],'WaitingForRemote')
        result=bridge.advance(True)
        return bridge,result

    def test_disabled_dispatch_has_no_files_or_calls(self):
        bridge=self.bridge()
        self.assertEqual(bridge.advance()['status'],'WaitingForApproval')
        self.assertFalse(bridge.directory.exists());self.assertEqual(self.calls,[])

    def test_remote_dispatch_poll_checkout_test_review_and_idempotence(self):
        bridge,result=self.dispatch_and_validate()
        self.assertEqual(result['status'],'AwaitingCodeReview')
        self.assertEqual(result['validatedHead'],SHA)
        self.assertTrue(any('refs/pull/7/head' in call for call in self.calls))
        self.assertTrue(any('unittest' in call for call in self.calls))
        calls=len(self.calls);self.assertEqual(bridge.advance(True),result);self.assertEqual(len(self.calls),calls)
        self.assertEqual(bridge.verify_review()['status'],'Verified')
        self.remote_sha='b'*40
        with self.assertRaisesRegex(ValueError,'changed'): bridge.verify_review()

    def test_running_remote_not_complete_and_poll_is_throttled(self):
        self.session_state='running';bridge=self.bridge();bridge.advance(True)
        self.assertEqual(bridge.advance(True)['status'],'WaitingForRemote')
        calls=len(self.calls);bridge.advance(True);self.assertEqual(len(self.calls),calls)

    def test_unmerged_code_does_not_release_dependencies(self):
        bridge,result=self.dispatch_and_validate();self.pr_state='OPEN'
        with self.assertRaisesRegex(ValueError,'Merge'): bridge.verify_review()

    def test_changed_head_during_checkout_is_rejected(self):
        self.remote_sha='b'*40
        _,result=self.dispatch_and_validate()
        self.assertEqual(result['status'],'Failed');self.assertIn('changed while fetching',result['error'])

    def test_validation_failure_does_not_complete(self):
        self.fail_validation=True
        bridge,result=self.dispatch_and_validate()
        self.assertEqual(result['status'],'Failed')
        self.fail_validation=False
        self.assertEqual(bridge.advance(True,revalidate=True)['status'],'AwaitingCodeReview')
        self.assertEqual(sum(call[1:3]==['agent-task','create'] for call in self.calls),1)

    def test_protected_runtime_changes_are_rejected(self):
        self.changed_path='tasks/queue.json'
        _,result=self.dispatch_and_validate()
        self.assertEqual(result['status'],'Failed');self.assertIn('protected',result['error'])

    def test_ambiguous_dispatch_cannot_be_submitted_twice(self):
        bridge=self.bridge();original=bridge.runner
        def ambiguous(args,**kwargs):
            result=original(args,**kwargs)
            if args[1:3]==['agent-task','create']: result.stdout='connection lost'
            return result
        bridge.runner=ambiguous
        self.assertEqual(bridge.advance(True)['status'],'NeedsInput')
        self.assertEqual(bridge.advance(True)['status'],'NeedsInput')
        self.assertEqual(sum(call[1:3]==['agent-task','create'] for call in self.calls),1)
        result=bridge.advance(True,bind_pr=URL,bind_session='session-7')
        self.assertEqual(result['status'],'AwaitingCodeReview')

    def test_changed_input_refuses_existing_receipt(self):
        bridge=self.bridge();bridge.advance(True)
        self.task['description']='Different task'
        with self.assertRaisesRegex(ValueError,'inputs changed'): self.bridge().advance(True)

    def test_github_forbidden_is_actionable_and_not_redispatched(self):
        bridge=self.bridge()
        def forbidden(args,**kwargs):
            self.calls.append(args)
            return SimpleNamespace(stdout='',stderr='failed to create job: 403 Forbidden',returncode=1)
        bridge.runner=forbidden
        result=bridge.advance(True)
        self.assertEqual(result['status'],'NeedsInput');self.assertIn('cloud-agent access',result['error'])
        bridge.advance(True);self.assertEqual(len(self.calls),1)

    def test_local_copilot_uses_isolated_checkout_and_publishes_draft(self):
        self.task['backend']='copilot-local'
        result=self.bridge().advance(True)
        self.assertEqual(result['status'],'AwaitingCodeReview')
        copilot=next(call for call in self.calls if call[0]=='copilot')
        self.assertIn('--no-remote',copilot);self.assertIn('--deny-tool=shell(git push)',copilot)
        self.assertIn('--trust-folder',copilot);self.assertIn('--name',copilot)
        self.assertNotIn('--session-id',copilot)
        self.assertIn('--draft',next(call for call in self.calls if call[1:3]==['pr','create']))
        self.assertTrue(any('HEAD:refs/heads/studio/task-test-' in ' '.join(call) for call in self.calls))

    def test_ollama_plan_has_explicit_review_before_children(self):
        self.task.update(backend='ollama',kind='plan',role='project_manager')
        plan={'tasks':[dict(key='research',title='Research',description='Find references',role='historical_research',backend='ollama'),dict(key='code',title='Code',description='Build menu',role='gameplay',backend='copilot-github',dependencies=['research'])]}
        bridge=self.bridge(http=lambda payload:{'choices':[{'message':{'content':json.dumps(plan)}}]})
        result=bridge.advance(True)
        self.assertEqual(result['status'],'AwaitingPlanReview')
        saved=json.loads(Path(result['resultPath']).read_text())
        self.assertEqual(saved['tasks'][1]['dependencies'],[saved['tasks'][0]['id']])
        self.assertEqual(saved['tasks'][1]['backend'],'copilot-local')
        self.assertEqual(self.calls,[])
        plan['tasks'][0]['dependencies']=['code']
        with self.assertRaisesRegex(ValueError,'Cyclic'): normalize_plan(plan,'TASK-TEST',bridge.source,self.config['roles'])

    def test_invalid_id_role_backend_and_plan_contracts(self):
        for key,value in [('id','../x'),('id','COM1'),('role','unknown'),('backend','shell')]:
            task={**self.task,key:value}
            with self.subTest(key=key,value=value),self.assertRaises(ValueError):validate(task,self.config)
        for plan in [{'tasks':[]},{'tasks':[{'key':'a'},{'key':'a'}]}]:
            with self.assertRaises(ValueError):normalize_plan(plan,'TASK-TEST',{},self.config['roles'])

    def test_invalid_code_backend_config_is_rejected(self):
        for value in ('shell','ollama',None):
            with self.subTest(value=value),self.assertRaisesRegex(ValueError,'default_code_backend'):
                validate(self.task,{**self.config,'default_code_backend':value})

    def test_planner_can_use_explicitly_configured_code_backend(self):
        step=dict(key='code',title='Code',description='Build',role='gameplay',backend='copilot-local')
        result=normalize_plan({'tasks':[step]},'PARENT',{'attachments':[],'projectPath':''},self.config['roles'],'copilot-github')
        self.assertEqual(result['tasks'][0]['backend'],'copilot-github')

    def test_pinokio_task_uses_role_tools_and_requires_result_review(self):
        self.task.update(backend='pinokio',role='character3d',toolCapability='image_to_3d',toolOperation='decode_settings',toolParameters={})
        with patch('pinokio_tools.Pinokio') as tools:
            tools.return_value.ensure.return_value={'app_id':'hunyuan','ready':True}
            def invoke(*args):
                (Path(args[-1])/'tool-result.json').write_text(json.dumps({'output':[256]}))
            tools.return_value.invoke.side_effect=invoke
            result=self.bridge().advance(True)
            self.assertEqual(result['status'],'AwaitingVisualReview')
            tools.return_value.ensure.assert_called_once()
            self.assertTrue(Path(result['resultPath']).is_file())

    def test_pinokio_role_cannot_launch_an_unassigned_tool(self):
        self.task.update(backend='pinokio',role='historical_research',toolCapability='image_to_3d',toolOperation='decode_settings')
        with patch('pinokio_tools.Pinokio') as tools:
            result=self.bridge().advance(True)
            self.assertEqual(result['status'],'Failed');self.assertIn('unavailable to this role',result['error'])
            tools.assert_not_called()

    def test_unregistered_pinokio_operation_does_not_launch_app(self):
        self.task.update(backend='pinokio',role='character3d',toolCapability='image_to_3d',toolOperation='invented')
        with patch('pinokio_tools.Pinokio') as tools:
            result=self.bridge().advance(True)
            self.assertEqual(result['status'],'NeedsInput')
            tools.return_value.ensure.assert_not_called()

    def test_pinokio_can_resume_recorded_tool_job_after_timeout(self):
        self.task.update(backend='pinokio',role='art_world',toolCapability='image_generation',toolOperation='generate_image',toolParameters={'prompt':'Blue prop'})
        from pinokio_tools import ToolUnavailable
        bridge=self.bridge()
        with patch('pinokio_tools.Pinokio') as tools:
            def pending(*args):
                (Path(args[-1])/'tool-call.json').write_text(json.dumps({'status':'Submitted','prompt_id':'recorded-id'}))
                raise ToolUnavailable('Still pending')
            tools.return_value.invoke.side_effect=pending
            self.assertEqual(bridge.advance(True)['status'],'NeedsInput')
            def ready(*args):(Path(args[-1])/'tool-result.json').write_text(json.dumps({'artifacts':[]}))
            tools.return_value.invoke.side_effect=ready
            self.assertEqual(bridge.advance(True,resume_tool=True)['status'],'AwaitingVisualReview')
            self.assertEqual(tools.return_value.invoke.call_count,2)

    def test_pinokio_ambiguous_dispatch_cannot_be_resumed_as_new_job(self):
        self.task.update(backend='pinokio',role='art_world',toolCapability='image_generation',toolOperation='generate_image',toolParameters={'prompt':'Blue prop'})
        from pinokio_tools import ToolUnavailable
        bridge=self.bridge()
        with patch('pinokio_tools.Pinokio') as tools:
            def interrupted(*args):
                (Path(args[-1])/'tool-call.json').write_text(json.dumps({'status':'Dispatching','prompt_id':'recorded-id'}))
                raise ToolUnavailable('Connection lost')
            tools.return_value.invoke.side_effect=interrupted
            bridge.advance(True)
            with self.assertRaisesRegex(ValueError,'ambiguous'):bridge.advance(True,resume_tool=True)
            self.assertEqual(tools.return_value.invoke.call_count,1)

    def test_pinokio_generation_uses_attached_reference(self):
        image=Path(self.temp.name)/'reference.png';image.write_bytes(b'reference')
        self.task.update(backend='pinokio',role='character3d',attachments=[str(image)],toolCapability='image_to_3d',toolOperation='generate_shape',toolParameters={})
        with patch('pinokio_tools.Pinokio') as tools:
            result=self.bridge().advance(True)
            self.assertEqual(result['status'],'AwaitingVisualReview')
            self.assertEqual(tools.return_value.invoke.call_args.args[2],{'image':{'local_file':str(image)}})

    def test_planner_keeps_pinokio_tool_contract(self):
        source={'attachments':[],'projectPath':''}
        step=dict(key='shape',title='Shape',description='Generate',role='character3d',backend='pinokio',toolCapability='image_to_3d',toolOperation='generate_shape',toolParameters={'steps':5})
        plan=normalize_plan({'tasks':[step]},'PARENT',source,self.config['roles'])
        self.assertEqual(plan['tasks'][0]['toolParameters'],{'steps':5})
        del step['toolCapability']
        with self.assertRaisesRegex(ValueError,'requires capability'):normalize_plan({'tasks':[step]},'PARENT',source,self.config['roles'])

    @unittest.skipUnless(shutil.which('git'),'Git required')
    def test_validation_runs_real_git_and_real_tests_in_isolated_checkout(self):
        checkout=Path(self.temp.name)/'real-checkout';checkout.mkdir()
        def git(*args):
            return subprocess.run(['git',*args],cwd=checkout,capture_output=True,text=True,check=True).stdout.strip()
        git('init');git('config','user.name','Studio Test');git('config','user.email','studio@example.invalid')
        (checkout/'app.py').write_text('def answer(): return 41\n')
        (checkout/'.gitignore').write_text('__pycache__/\n')
        git('add','.');git('commit','-m','base');git('update-ref','refs/remotes/origin/main','HEAD')
        (checkout/'app.py').write_text('def answer(): return 42\n')
        (checkout/'tests').mkdir()
        (checkout/'tests/test_app.py').write_text('import unittest\nfrom app import answer\nclass AppTest(unittest.TestCase):\n def test_answer(self): self.assertEqual(answer(),42)\n')
        git('add','.');git('commit','-m','task')
        bridge=Bridge(self.task,self.config);bridge.path.mkdir(parents=True)
        bridge.validate_checkout(checkout,{})
        evidence=json.loads((bridge.path/'validation.json').read_text())
        self.assertEqual(evidence['head'],git('rev-parse','HEAD'))
        self.assertEqual(evidence['status'],'pass')
        (checkout/'tasks').mkdir();(checkout/'tasks/queue.json').write_text('[]')
        git('add','.');git('commit','-m','invalid runtime edit')
        with self.assertRaisesRegex(ValueError,'protected'):bridge.validate_checkout(checkout,{})

if __name__=='__main__': unittest.main()
