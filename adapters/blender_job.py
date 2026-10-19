import argparse,json,subprocess,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
CFG=json.loads((ROOT/'config'/'studio.json').read_text(encoding='utf-8-sig'))
def run(job_path,approve_write=False):
 job=json.loads(Path(job_path).read_text(encoding='utf-8-sig')); exe=Path(CFG['paths']['blender']); ws=Path(CFG['paths']['workspace'])/'blender';ws.mkdir(parents=True,exist_ok=True)
 if job.get('write_asset') and not approve_write: raise SystemExit('Approval required: write_blender_asset')
 out=ws/(job.get('output_name','job')+'.blend'); script=ws/'_job.py'
 code="import bpy,json\nprint('AI_STUDIO_JOB_START')\nbpy.ops.wm.read_factory_settings(use_empty=True)\n"
 if job.get('type')=='skeleton_stub':
  bones=job.get('bones',['root','pelvis','spine_01','spine_02','neck_01','head'])
  code+="bpy.ops.object.armature_add(enter_editmode=True)\nobj=bpy.context.object\nobj.name='SK_1864_Human'\narm=obj.data\nfirst=arm.edit_bones[0];first.name='"+bones[0]+"'\nprev=first\n"
  for b in bones[1:]: code+=f"b=arm.edit_bones.new('{b}');b.head=prev.tail;b.tail=(prev.tail.x,prev.tail.y,prev.tail.z+0.1);b.parent=prev;prev=b\n"
 code+="bpy.ops.object.mode_set(mode='OBJECT') if bpy.context.object and bpy.context.object.mode!='OBJECT' else None\n"
 if job.get('write_asset'): code+=f"bpy.ops.wm.save_as_mainfile(filepath=r'{str(out)}')\n"
 code+="print('AI_STUDIO_JOB_OK')\n"
 script.write_text(code,encoding='utf-8')
 p=subprocess.run([str(exe),'--background','--factory-startup','--python',str(script)],capture_output=True,text=True,timeout=300)
 evidence=ws/(Path(job_path).stem+'-evidence.txt');evidence.write_text(p.stdout+'\n'+p.stderr,encoding='utf-8')
 print(p.stdout);print('Evidence:',evidence);print('Output:',out if job.get('write_asset') else 'dry-run');raise SystemExit(p.returncode)
if __name__=='__main__':
 ap=argparse.ArgumentParser();ap.add_argument('job');ap.add_argument('--approve-write',action='store_true');a=ap.parse_args();run(a.job,a.approve_write)
