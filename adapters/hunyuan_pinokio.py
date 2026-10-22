"""Image-to-GLB entry point using the shared Pinokio launcher/API adapter."""
import argparse
import json
from pathlib import Path
import sys
from pinokio_tools import Pinokio,read_json,ROOT

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image',type=Path,required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--config',type=Path,default=ROOT/'config/pinokio-tools.json')
    parser.add_argument('--approve-launch',action='store_true')
    args=parser.parse_args()
    try:
        if not args.approve_launch:raise ValueError('Pinokio generation requires explicit tool execution approval')
        tools=Pinokio(read_json(args.config))
        state=tools.ensure('image_to_3d',args.evidence,approve=True)
        result=tools.invoke('image_to_3d','generate_shape',{'image':{'local_file':str(args.image)}},state,args.evidence)
        print(json.dumps({'status':'QueuedForBlender','output':result['artifacts'][0]['path'],'resultPath':str(args.evidence/'tool-result.json'),'ref':state.get('ref')}))
        return 0
    except Exception as error:
        print(json.dumps({'status':'NeedsInput','error':str(error)}));return 1

if __name__=='__main__':sys.exit(main())
