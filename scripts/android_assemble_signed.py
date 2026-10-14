"""Assemble checksummed signed APK chunks in CI; no signing secret is needed."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
from android_fetch_signed import SafeRedirect, REPOSITORY
from urllib.request import Request, build_opener


def assemble(release_id, output):
    output.mkdir(parents=True, exist_ok=True)
    def get(path, accept='application/vnd.github+json'):
        req = Request('https://api.github.com/repos/'+REPOSITORY+path, headers={'Authorization':'Bearer '+os.environ['GH_TOKEN'],
            'Accept':accept,'X-GitHub-Api-Version':'2022-11-28','User-Agent':'Animan-APK-assembly'})
        with build_opener(SafeRedirect()).open(req,timeout=60) as r: return r.read()
    release=json.loads(get('/releases/'+str(release_id)))
    assert release['draft'] and release['tag_name']=='android-v0.1.0-beta.1'
    assets={a['name']:a for a in release['assets']}
    manifest=json.loads(get('/releases/assets/'+str(assets['Android-apk-parts.json']['id']),'application/octet-stream'))
    assert manifest['filename']=='Animan-v0.1.0-Android-arm64.apk'
    target=output/manifest['filename']
    with target.open('wb') as file:
        for index, part in enumerate(manifest['parts'],1):
            assert part['name']==f'Android-signed-apk.part{index:03d}'
            data=get('/releases/assets/'+str(assets[part['name']]['id']),'application/octet-stream')
            assert len(data)==part['size'] and hashlib.sha256(data).hexdigest()==part['sha256']
            file.write(data)
    assert target.stat().st_size==manifest['size']
    assert hashlib.file_digest(target.open('rb'),'sha256').hexdigest()==manifest['sha256']
    tools=Path(os.environ['ANDROID_HOME'])/'build-tools/35.0.0'
    cert=subprocess.check_output([str(tools/'apksigner'),'verify','--print-certs',str(target)],text=True)
    info=json.loads(get('/releases/assets/'+str(assets['Android-build-info.json']['id']),'application/octet-stream'))
    assert info['signing_certificate_sha256'] in cert and not info['validation_key_only']
    subprocess.run([str(tools/'zipalign'),'-c','-P','16','4',str(target)],check=True)
    subprocess.run(['gh','release','upload','android-v0.1.0-beta.1',str(target),'--clobber','--repo',REPOSITORY],check=True)
    print('Checksummed APK assembled and verified; release remains a draft')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('release_id',type=int);parser.add_argument('output',type=Path)
    args=parser.parse_args();assemble(args.release_id,args.output)
