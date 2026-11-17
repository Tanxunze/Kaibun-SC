"""Offline deployment checks; never prints secrets or calls paid providers."""
import argparse
import json
import shutil
import sys
from pathlib import Path
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import ROOT, data_root, characters_path_from_env, load_environment, project_path

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--running', action='store_true', help='Also require the frontend proxy and backend health endpoint to respond')
    args = parser.parse_args()
    load_environment()
    import os
    from support.config import LLMSettings
    from support.characters import load_characters
    failures = 0
    try:
        settings = LLMSettings.optional_from_env("CHAT")
        if settings:
            print('OK model configuration:', settings.protocol, settings.model)
        else:
            print('OK local script import (optional writing model unconfigured)')
    except Exception:
        print('FAIL model configuration: check CHAT_LLM_BASE_URL/API_KEY/MODEL/PROTOCOL')
        failures += 1
    try:
        characters = load_characters(characters_path_from_env())
        print('OK characters:', len(characters), 'voice references:', sum(bool(c.voice_id) for c in characters.values()))
    except Exception:
        print('FAIL character configuration')
        failures += 1
    print(('OK' if shutil.which('node') else 'FAIL') + ' Node.js')
    failures += int(not shutil.which('node'))
    print('OK data directory:', data_root())
    assets = project_path(os.environ.get('KAIBUN_ASSET_ROOT') or 'assets')
    manifest = assets.parent / 'spine_manifest.json'
    print(('AVAILABLE' if manifest.exists() else 'OPTIONAL, absent') + ' stand manifest')
    print(('AVAILABLE' if (ROOT / 'frontend/public/vendor/spine-3.6/spine-webgl.js').is_file() else 'OPTIONAL, absent') + ' Spine runtime')
    print(('CONFIGURED' if os.environ.get('FISH_AUDIO_API_KEY') else 'OPTIONAL, absent') + ' TTS key (value hidden)')
    print(('BUILT' if (ROOT / 'frontend/.next/BUILD_ID').exists() else 'NOT BUILT') + ' frontend')
    if args.running:
        try:
            with urllib.request.urlopen('http://127.0.0.1:3010/api/kaibun/health', timeout=5) as response:
                if not json.load(response).get('ok'):
                    raise ValueError('health failed')
            print('OK local frontend -> backend connection')
        except Exception:
            print('FAIL local services: start them first, then inspect .runtime/*.log')
            failures += 1
    print('Checks complete. No provider requests were made.')
    return 1 if failures else 0

if __name__ == '__main__':
    raise SystemExit(main())
