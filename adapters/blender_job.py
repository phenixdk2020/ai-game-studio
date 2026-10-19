import argparse,json,re,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CFG=json.loads((ROOT/'config'/'studio.json').read_text(encoding='utf-8-sig'))
DEFAULT_BONES=['root','pelvis','spine_01','spine_02','neck_01','head']

def validate_job(job):
 if not isinstance(job,dict):raise ValueError('Blender job must be a JSON object')
 if job.get('type')!='skeleton_stub':raise ValueError("Unsupported Blender job type; expected 'skeleton_stub'")
 if 'write_asset' in job and not isinstance(job['write_asset'],bool):raise ValueError("'write_asset' must be a boolean")
 name=job.get('output_name','job')
 if not isinstance(name,str) or not name or name in {'.','..'} or not re.fullmatch(r'[A-Za-z0-9_.-]+',name):raise ValueError("'output_name' must be a simple filename without path separators")
 bones=job.get('bones',DEFAULT_BONES)
 if not isinstance(bones,list) or not bones or any(not isinstance(b,str) or not b.strip() or any(ord(c)<32 for c in b) for b in bones):raise ValueError("'bones' must be a non-empty list of valid names")
 if len(set(bones))!=len(bones):raise ValueError("'bones' must not contain duplicate names")
 return {**job,'output_name':name,'write_asset':job.get('write_asset',False),'bones':bones}

def build_script(job,out):
 code="import bpy,json\nprint('AI_STUDIO_JOB_START')\nbpy.ops.wm.read_factory_settings(use_empty=True)\n"
 if job['type']=='skeleton_stub':
  bones=job['bones']
  code+="bpy.ops.object.armature_add(enter_editmode=True)\nobj=bpy.context.object\nobj.name='SK_1864_Human'\narm=obj.data\nfirst=arm.edit_bones[0];first.name="+json.dumps(bones[0])+"\nprev=first\n"
  for b in bones[1:]: code+=f"b=arm.edit_bones.new({json.dumps(b)});b.head=prev.tail;b.tail=(prev.tail.x,prev.tail.y,prev.tail.z+0.1);b.parent=prev;prev=b\n"
 code+="bpy.ops.object.mode_set(mode='OBJECT') if bpy.context.object and bpy.context.object.mode!='OBJECT' else None\n"
 if job['write_asset']: code+=f"bpy.ops.wm.save_as_mainfile(filepath={json.dumps(str(out))})\n"
 code+="print('AI_STUDIO_JOB_OK')\n"
 return code

def run(job_path,approve_write=False,config=None,process_runner=None):
 job=validate_job(json.loads(Path(job_path).read_text(encoding='utf-8-sig')))
 if job['write_asset'] and not approve_write: raise SystemExit('Approval required: write_blender_asset')
 cfg=config or CFG
 exe=Path(cfg['paths']['blender']);ws=Path(cfg['paths']['workspace'])/'blender';ws.mkdir(parents=True,exist_ok=True)
 out=ws/(job['output_name']+'.blend');script=ws/'_job.py'
 script.write_text(build_script(job,out),encoding='utf-8')
 runner=process_runner or subprocess.run
 p=runner([str(exe),'--background','--factory-startup','--python',str(script)],capture_output=True,text=True,timeout=300)
 evidence=ws/(Path(job_path).stem+'-evidence.txt');evidence.write_text(p.stdout+'\n'+p.stderr,encoding='utf-8')
 print(p.stdout);print('Evidence:',evidence);print('Output:',out if job['write_asset'] else 'dry-run');raise SystemExit(p.returncode)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('job');ap.add_argument('--approve-write',action='store_true');a=ap.parse_args();run(a.job,a.approve_write)
