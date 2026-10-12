import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


class DeploymentTests(unittest.TestCase):
    def test_launcher_imports_backend_from_another_working_directory(self):
        data=ROOT/'data'
        data.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=data,prefix='launcher-test-') as temporary:
            self.assertTrue(Path(temporary).resolve().is_relative_to(data.resolve()))
            environment=os.environ.copy()
            environment.update(BOT_TOKEN='',WEBHOOK_SECRET='test-secret',AUTO_SETUP_TELEGRAM='false',PAYMENTS_ENABLED='false',DATABASE_PATH=str(Path(temporary)/'test.sqlite3'),SQLITE_TMPDIR=temporary,TEMP=temporary,TMP=temporary)
            code='''import runpy,sys
from unittest.mock import patch
from pathlib import Path
entry=Path(sys.argv[1]).resolve()
with patch('uvicorn.run') as launch:
 runpy.run_path(str(entry),run_name='__main__')
 assert launch.call_args.args[0].title=='Brainrot Freebie API'
 assert launch.call_args.kwargs['host']=='0.0.0.0'
 assert Path.cwd()==entry.parent
print('launcher-ok')
'''
            result=subprocess.run([sys.executable,'-c',code,str(ROOT/'main.py')],cwd=temporary,env=environment,capture_output=True,text=True,timeout=20)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('launcher-ok',result.stdout)

    def test_catalog_assets_and_modules_keep_expected_paths(self):
        import json
        for module in ('app','auth','economy','fair','risk','service','store','verify'):
            self.assertTrue((ROOT/f'backend/{module}.py').is_file())
        catalog=json.loads((ROOT/'backend/catalog.json').read_text(encoding='utf-8'))
        for item in catalog['items']+catalog['cases']:
            self.assertTrue((ROOT/'web'/item['image']).is_file(),item['image'])
        self.assertTrue((ROOT/'web/img/logotype.png').is_file())
        self.assertTrue((ROOT/'web/index.html').is_file())


if __name__=='__main__':unittest.main()
