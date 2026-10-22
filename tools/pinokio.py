"""Public Pinokio tool discovery/inspection CLI."""
from pathlib import Path
import runpy
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'adapters'))
runpy.run_module('pinokio_tools',run_name='__main__')
