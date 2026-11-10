"""公开包解析/安装入口；子进程不继承真实环境，无pip配置、netrc或keyring。"""
import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
script="""
import sys
from pathlib import Path
def audit(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)):
  p=Path(args[0].decode() if isinstance(args[0],bytes) else args[0])
  if p.name in ('.env','.netrc','pip.conf','secrets.toml') or p.name.startswith('.env.'):
   raise PermissionError('credential/config access denied')
sys.addaudithook(audit)
from pip._internal.network.session import PipSession
original=PipSession.__init__
def init(self,*args,**kwargs):
 original(self,*args,**kwargs); self.trust_env=False
PipSession.__init__=init
from pip._internal.cli.main import main
raise SystemExit(main(sys.argv[1:]))
"""
args=['install','--no-cache-dir','--disable-pip-version-check','--keyring-provider','disabled','--index-url','https://pypi.org/simple']
if '--install' not in sys.argv:args+=['--dry-run','--report','/tmp/engineering_rag_dependency_plan.json']
args+=['sentence-transformers==3.4.1','transformers==4.48.3','torch==2.6.0','numpy==2.5.4']
os.execve(str(ROOT/'.venv/bin/python'),[str(ROOT/'.venv/bin/python'),'-c',script,*args],{'PATH':'/usr/bin:/bin','PIP_CONFIG_FILE':'/dev/null','PYTHONNOUSERSITE':'1'})
