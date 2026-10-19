import argparse,json,subprocess
from pathlib import Path
import re
ROOT=Path(__file__).resolve().parents[1]
CFG=json.loads((ROOT/'config'/'studio.json').read_text(encoding='utf-8-sig'))

DEFAULT_BONES=['root','pelvis','spine_01','spine_02','neck_01','head']

def validate_job(job):
 if not isinstance(job,dict): raise ValueError('Blender job must be a JSON object')
 if job.get('type')!='skeleton_stub': raise ValueError('Unsupported Blender job type')
 if not isinstance(job.get('write_asset',False),bool): raise ValueError('write_asset must be a boolean')
 name=job.get('output_name','job')
 if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,119}',name) or name in ('.','..'):
  raise ValueError('output_name must be a safe file name')
 bones=job.get('bones',DEFAULT_BONES)
 if not isinstance(bones,list) or not bones or any(not isinstance(b,str) or not b.strip() for b in bones):
  raise ValueError('bones must be a non-empty list of names')
 if len(set(bones))!=len(bones): raise ValueError('bones must not contain duplicate names')

def build_script(job,out):
 bones=job.get('bones',DEFAULT_BONES)
 code=[
  'import bpy',
  "print('AI_STUDIO_JOB_START')",
  'bpy.ops.wm.read_factory_settings(use_empty=True)',
  'bpy.ops.object.armature_add(enter_editmode=True)',
  "obj=bpy.context.object",
  "obj.name='SK_1864_Human'",
  'arm=obj.data',
  'first=arm.edit_bones[0]',
  f'first.name={json.dumps(bones[0])}',
  'prev=first',
 ]
 for bone in bones[1:]:
  code.extend([
   f'b=arm.edit_bones.new({json.dumps(bone)})',
   'b.head=prev.tail',
   'b.tail=(prev.tail.x,prev.tail.y,prev.tail.z+0.1)',
   'b.parent=prev',
   'prev=b',
  ])
 code.append("bpy.ops.object.mode_set(mode='OBJECT') if bpy.context.object and bpy.context.object.mode!='OBJECT' else None")
 if job.get('write_asset'): code.append(f'bpy.ops.wm.save_as_mainfile(filepath={json.dumps(str(out))})')
 code.append("print('AI_STUDIO_JOB_OK')")
 return '\n'.join(code)+'\n'

def run(job_path,approve_write=False):
 job=json.loads(Path(job_path).read_text(encoding='utf-8-sig'))
 validate_job(job)
 if job.get('write_asset') and not approve_write: raise SystemExit('Approval required: write_blender_asset')
 exe=Path(CFG['paths']['blender']); ws=Path(CFG['paths']['workspace'])/'blender'
 out=ws/(job.get('output_name','job')+'.blend'); script=ws/'_job.py'
 ws.mkdir(parents=True,exist_ok=True)
 code=build_script(job,out)
 script.write_text(code,encoding='utf-8')
 p=subprocess.run([str(exe),'--background','--factory-startup','--python',str(script)],capture_output=True,text=True,timeout=300)
 evidence=ws/(Path(job_path).stem+'-evidence.txt');evidence.write_text(p.stdout+'\n'+p.stderr,encoding='utf-8')
 print(p.stdout);print('Evidence:',evidence);print('Output:',out if job.get('write_asset') else 'dry-run');raise SystemExit(p.returncode)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('job');ap.add_argument('--approve-write',action='store_true');a=ap.parse_args();run(a.job,a.approve_write)
