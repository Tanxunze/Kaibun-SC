"""Fetch optional stand assets using the same public catalog as Eidolon-SC.

Default: only configured default outfits. --all downloads the full selected catalog.
Requests are serial and at least one second apart; access restrictions stop the run.
"""
import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from paths import ROOT, characters_path_from_env, load_environment, project_path
from support.characters import load_characters
from asset_index import atomic_json

API = 'https://api.shinycolors.moe'
CDN = 'https://cf-static.shinycolors.moe'
RUNTIME = 'https://raw.githubusercontent.com/EsotericSoftware/spine-runtimes/654c20e5b0e523040b6366bbd1042510d2645134/spine-ts/build/spine-webgl.js'
RUNTIME_HASH = '2883daee81ae60b25f6205b83feb82b76812bf63cfdf0886f04f390b12891794'
OUTFIT = re.compile(r'(stand|stand_costume)/\d{10}\Z')

class SourceError(RuntimeError):
    pass

class Fetcher:
    def __init__(self, interval):
        self.interval, self.last = max(1.0, interval), None
        self.client = httpx.Client(timeout=60, follow_redirects=True, headers={'User-Agent': 'kaibun optional stand sync (serial, one request per second)'})

    def get(self, url):
        if self.last is not None:
            time.sleep(max(0, self.last + self.interval - time.monotonic()))
        try:
            response = self.client.get(url)
            if response.status_code == 404:
                return None
            if response.status_code in (401, 403, 429):
                raise SourceError(f'来源返回 HTTP {response.status_code}，已停止；请勿连续重试或绕过限制')
            response.raise_for_status()
            return response.content
        except httpx.HTTPError as error:
            raise SourceError(f'素材来源暂不可用（{type(error).__name__}），已保存的文件保留') from None
        finally:
            self.last = time.monotonic()

def valid_file(name, data):
    if not data:
        return False
    if name.endswith('.json'):
        try:
            return isinstance(json.loads(data), dict)
        except (ValueError, UnicodeDecodeError):
            return False
    if name.endswith('.png'):
        return data.startswith(b'\x89PNG\r\n\x1a\n') or data[:4] == b'RIFF' and data[8:12] == b'WEBP'
    return bool(data.strip()) and not data.lstrip().startswith(b'<')

def save_bytes(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_suffix(path.suffix + '.part')
    part.write_bytes(data)
    part.replace(path)

def fetch_outfit(fetcher, assets, oid, source):
    directory = assets / 'spine/idols' / oid
    for name in ('data.json', 'data.atlas', 'data.png'):
        target = directory / name
        if target.is_file() and valid_file(name, target.read_bytes()):
            continue
        data = fetcher.get(source + name)
        if not valid_file(name, data):
            return False
        save_bytes(target, data)
    # Some upstream atlases call the identical texture date.png; verify before renaming.
    atlas = directory / 'data.atlas'
    lines = atlas.read_text(encoding='utf-8').splitlines(keepends=True)
    for index, line in enumerate(lines):
        page = line.strip()
        following = next((s.strip() for s in lines[index + 1:] if s.strip()), '')
        if page and ':' not in page and following.startswith('size:') and page != 'data.png':
            if '/' in page or '\\' in page or fetcher.get(source + page) != (directory / 'data.png').read_bytes():
                return False
            lines[index] = line.replace(page, 'data.png')
    save_bytes(atlas, ''.join(lines).encode())
    return True

def main():
    load_environment()
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--character', action='append', default=[], help='Character id; repeat for multiple characters')
    parser.add_argument('--all', action='store_true', help='Download all outfits, rather than configured defaults')
    parser.add_argument('--runtime', action='store_true', help='Only fetch the pinned optional Spine runtime; applicable licensing is your responsibility')
    parser.add_argument('--interval', type=float, default=1.1)
    args = parser.parse_args()
    fetcher = Fetcher(args.interval)
    try:
        if args.runtime:
            data = fetcher.get(RUNTIME)
            if not data or hashlib.sha256(data).hexdigest() != RUNTIME_HASH:
                raise SourceError('运行库缺失或校验失败，未写入文件')
            path = ROOT / 'frontend/public/vendor/spine-3.6/spine-webgl.js'
            save_bytes(path, data)
            print('Spine runtime downloaded; SHA-256 verified. See LICENSING.md.')
            return 0
        characters = load_characters(characters_path_from_env())
        unknown = set(args.character) - characters.keys()
        if unknown:
            parser.error('未知人物：' + ', '.join(sorted(unknown)))
        selected = [c for c in characters.values() if not args.character or c.id in args.character]
        assets = project_path(os.environ.get('KAIBUN_ASSET_ROOT') or 'assets')
        manifest = assets.parent / 'spine_manifest.json'
        entries = {r['path']: r for r in json.loads(manifest.read_text(encoding='utf-8'))} if manifest.exists() else {}
        missing, done = [], 0
        try:
            for character in selected:
                if args.all:
                    raw = fetcher.get(f'{API}/spine/dresslist?idolId={character.idol_id}')
                    rows = json.loads(raw) if raw else None
                    if not isinstance(rows, list):
                        raise SourceError('衣装目录格式有误，已停止')
                    outfits = []
                    for row in rows:
                        for asset in (row.get('assets') or {}).get('idols') or []:
                            oid = f"{asset.get('type')}/{row.get('enzaId')}"
                            if not OUTFIT.fullmatch(oid):
                                continue
                            source_path = asset.get('path') or 'spine/idols/' + oid
                            parsed = urlsplit(source_path)
                            if parsed.scheme or parsed.netloc or '..' in source_path.split('/') or not source_path.startswith('spine/idols/'):
                                raise SourceError('目录含无效素材路径，已停止')
                            outfits.append((oid, CDN + '/' + source_path.rstrip('/') + '/', row.get('dressName', '')))
                else:
                    oid = character.default_outfit
                    outfits = [(oid, CDN + '/spine/idols/' + oid + '/', '默认衣装')] if oid and OUTFIT.fullmatch(oid) else []
                for oid, source, label in outfits:
                    if not fetch_outfit(fetcher, assets, oid, source):
                        missing.append(oid)
                        print('MISSING', character.id, oid, flush=True)
                        continue
                    key = 'spine/idols/' + oid + '/'
                    previous = entries.get(key, {})
                    entries[key] = dict(previous, path=key, category=oid.split('/')[0], idolId=character.idol_id,
                                        idolName=character.name, enzaId=oid.split('/')[1], dressName=(label if args.all else previous.get('dressName') or label), source_url=source)
                    atomic_json(manifest, list(entries.values()))
                    done += 1
                    print('READY', character.id, oid, flush=True)
        finally:
            if entries:
                atomic_json(manifest, list(entries.values()))
        print(f'FINISHED ready={done} missing={len(missing)} manifest={manifest}')
        return 2 if missing else 0
    except (SourceError, ValueError, OSError) as error:
        print(str(error), file=sys.stderr)
        return 2
    finally:
        fetcher.client.close()

if __name__ == '__main__':
    raise SystemExit(main())
