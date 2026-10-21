"""Download only public signing outputs from this repository's draft release."""
import argparse
import hashlib
import json
import os
from pathlib import Path
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.parse import urlparse

REPOSITORY = 'loeuf237/animelab'
NAMES = {'AnimeLab-v0.1.0-Android-arm64.apk': 'AnimeLab-Android-under-test.apk',
         'AnimeLab-instrumentation.apk': 'AnimeLab-instrumentation.apk',
         'Android-build-info.json': 'Android-build-info.json', 'SHA256SUMS.txt': 'SHA256SUMS.txt'}

class SafeRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = super().redirect_request(req, fp, code, msg, headers, newurl)
        if target and urlparse(newurl).hostname != 'api.github.com': target.remove_header('Authorization')
        return target


def fetch(release_id, output):
    output.mkdir(parents=True, exist_ok=True)
    token = os.environ['GH_TOKEN']
    def get(path, accept='application/vnd.github+json'):
        request = Request('https://api.github.com/repos/' + REPOSITORY + path,
            headers={'Authorization': 'Bearer ' + token, 'Accept': accept,
                     'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'AnimeLab-signed-APK-validation'})
        with build_opener(SafeRedirect()).open(request, timeout=60) as response: return response.read()
    release = json.loads(get('/releases/' + str(release_id)))
    assert release['draft'] and release['tag_name'] == 'android-v0.1.0-beta.1'
    assets = {a['name']: a for a in json.loads(get('/releases/' + str(release_id) + '/assets?per_page=100'))}
    aliases = {name.replace('AnimeLab', 'Animan'): target for name, target in NAMES.items()}
    for name, destination in NAMES.items():
        asset = assets.get(name) or assets[name.replace('AnimeLab', 'Animan')]
        data = get('/releases/assets/' + str(asset['id']), 'application/octet-stream')
        if asset.get('digest'): assert asset['digest'] == 'sha256:' + hashlib.sha256(data).hexdigest()
        (output / destination).write_bytes(data)
    info = json.loads((output / 'Android-build-info.json').read_text())
    assert not info['validation_key_only'] and info['signing_method'] == 'local_apksigner'
    for line in (output / 'SHA256SUMS.txt').read_text().splitlines():
        digest, name = line.split('  ', 1)
        destination = NAMES.get(name, aliases.get(name, name))
        assert destination in NAMES.values()
        assert hashlib.file_digest((output / destination).open('rb'), 'sha256').hexdigest() == digest
    print('Dedicated signed APK downloaded and hashes verified; private identity was not transferred')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('release_id', type=int)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    fetch(args.release_id, args.output)
