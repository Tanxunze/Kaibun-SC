"""Start Kaibun locally; press Ctrl+C in this terminal to stop both services."""
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True)

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rebuild', action='store_true')
    args = parser.parse_args()
    if not (ROOT / '.env').is_file():
        shutil.copyfile(ROOT / '.env.example', ROOT / '.env')
        print('Created .env. Fill CHAT_LLM_API_KEY and CHAT_LLM_MODEL, then start again.')
        return 1
    uv = shutil.which('uv')
    node, npm = shutil.which('node'), shutil.which('npm.cmd' if os.name == 'nt' else 'npm')
    python = ROOT / ('backend/.venv/Scripts/python.exe' if os.name == 'nt' else 'backend/.venv/bin/python')
    if not node or not npm:
        raise RuntimeError('Install Node.js 22+ (including npm), then reopen your terminal.')
    if uv:
        run([uv, 'sync', '--locked'], ROOT / 'backend')
    elif not python.is_file():
        raise RuntimeError('Install uv, then reopen your terminal: https://docs.astral.sh/uv/getting-started/installation/')
    # Validate configuration without printing credentials or making provider requests.
    check = "from paths import load_environment; load_environment(); from support.config import LLMSettings; LLMSettings.chat_from_env(); import os,json; print(json.dumps({'port':int(os.environ.get('KAIBUN_PORT') or '8011')}))"
    result = subprocess.run([str(python), '-c', check], cwd=ROOT / 'backend', capture_output=True, text=True)
    if result.returncode:
        print('Backend configuration/dependencies are incomplete. Run: cd backend; uv sync --locked')
        print('Check CHAT_LLM_BASE_URL, CHAT_LLM_API_KEY and CHAT_LLM_MODEL in .env.')
        return 1
    backend_port = json.loads(result.stdout)['port']
    if not 1 <= backend_port <= 65535 or backend_port == 3010:
        raise RuntimeError('KAIBUN_PORT must be a valid port other than frontend port 3010.')
    for port in (backend_port, 3010):
        with socket.socket() as probe:
            if probe.connect_ex(('127.0.0.1', port)) == 0:
                raise RuntimeError(f'Port {port} is already in use. Close the existing service first.')
    frontend = ROOT / 'frontend'
    if not (frontend / 'node_modules/next/package.json').exists():
        run([npm, 'ci'], frontend)
    if args.rebuild or not (frontend / '.next/BUILD_ID').is_file():
        run([npm, 'run', 'build'], frontend)
    runtime = ROOT / '.runtime'
    runtime.mkdir(exist_ok=True)
    processes, logs = [], []
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    try:
        for name, command, cwd in [
            ('backend', [str(python), 'server.py'], ROOT / 'backend'),
            ('frontend', [node, str(frontend / 'node_modules/next/dist/bin/next'), 'start', '--hostname', '127.0.0.1', '--port', '3010'], frontend),
        ]:
            log = (runtime / (name + '.log')).open('a', encoding='utf-8')
            logs.append(log)
            processes.append(subprocess.Popen(command, cwd=cwd, stdout=log, stderr=log, creationflags=flags))
        ready = False
        for _ in range(120):
            if any(p.poll() is not None for p in processes):
                raise RuntimeError('A service exited. Read .runtime/backend.log and .runtime/frontend.log.')
            try:
                with urllib.request.urlopen('http://127.0.0.1:3010/api/kaibun/health', timeout=2) as response:
                    ready = response.status == 200
                if ready:
                    break
            except (OSError, ValueError):
                pass
            time.sleep(.5)
        if not ready:
            raise RuntimeError('Startup timed out. Read .runtime/backend.log and .runtime/frontend.log.')
        print('Kaibun is ready: http://localhost:3010', flush=True)
        print('Keep this terminal open. Press Ctrl+C to stop both services.', flush=True)
        while all(p.poll() is None for p in processes):
            time.sleep(1)
        raise RuntimeError('A service exited. Check .runtime/*.log.')
    except KeyboardInterrupt:
        print('\nStopping Kaibun...')
        return 0
    finally:
        for process in processes:
            if process.poll() is not None:
                continue
            if os.name == 'nt':
                # Kill only a child service created by this launcher, including its descendants.
                subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, creationflags=flags)
            else:
                process.terminate()
            process.wait(timeout=15)
        for log in logs:
            log.close()

if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (RuntimeError, OSError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
