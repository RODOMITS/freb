"""Bothost entrypoint: bot, Mini App and API run in one process."""
import os
import secrets
import sys
import importlib
from pathlib import Path

import uvicorn


def configure(root):
    if os.name=='posix': os.umask(0o077)
    env_file=root/'.env'
    if env_file.exists():
        for line in env_file.read_text(encoding='utf-8-sig').splitlines():
            line=line.strip()
            if line and not line.startswith('#') and '=' in line:
                key,value=line.split('=',1)
                os.environ.setdefault(key.strip(),value.strip().strip('"').strip("'"))
    database=Path(os.getenv('DATABASE_PATH',str(root/'data/freebie.sqlite3')))
    database.parent.mkdir(parents=True,exist_ok=True)
    os.environ.setdefault('DATABASE_PATH',str(database))
    if not os.getenv('WEBHOOK_SECRET'):
        secret_file=database.parent/'.webhook-secret'
        if not secret_file.exists():
            secret_file.write_text(secrets.token_urlsafe(32),encoding='utf-8')
            secret_file.chmod(0o600)
        os.environ['WEBHOOK_SECRET']=secret_file.read_text(encoding='utf-8').strip()
    os.environ.setdefault('AUTO_SETUP_TELEGRAM','true')
    if not os.getenv('BOT_TOKEN'):
        print('BOT_TOKEN is not configured: Telegram login and purchases are disabled.')
    elif not os.getenv('PUBLIC_URL','').startswith('https://'):
        raise SystemExit('Set PUBLIC_URL to the HTTPS domain shown in Bothost.')


if __name__=='__main__':
    project_root=Path(__file__).resolve().parent
    if not (project_root/'backend/app.py').is_file():
        raise SystemExit('Deployment is incomplete: backend/app.py must be next to main.py inside the backend folder. Upload and extract the entire Bothost.zip, preserving folders, then redeploy.')
    sys.path.insert(0,str(project_root))
    os.chdir(project_root)
    configure(project_root)
    application=importlib.import_module('backend.app').app
    if os.getenv('FORWARDED_ALLOW_IPS','127.0.0.1').strip()=='*':
        raise SystemExit('FORWARDED_ALLOW_IPS must list trusted proxy IPs/CIDRs, not *. Ask Bothost for the proxy address.')
    uvicorn.run(application,host='0.0.0.0',port=int(os.getenv('PORT','8000')),workers=1,proxy_headers=True,forwarded_allow_ips=os.getenv('FORWARDED_ALLOW_IPS','127.0.0.1'),limit_concurrency=128,backlog=128,timeout_keep_alive=5,server_header=False)
