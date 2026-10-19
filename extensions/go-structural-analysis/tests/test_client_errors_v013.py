"""Malformed worker responses must become actionable errors in the host UI."""
import json
from types import SimpleNamespace
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parents[1]/'go_structural_analysis'))
import client
from model import benchmark

@pytest.mark.parametrize('stdout,message',[
    ('not json','Invalid solver JSON'),
    ('[]','response object'),
    ('{"protocol":2,"ok":true}','protocol mismatch'),
    ('{"protocol":1,"ok":false,"error":"specific failure"}','specific failure'),
    ('{"protocol":1,"ok":true,"result":[]}','result structure'),
    ('{"protocol":1,"ok":true,"result":{"cases":[]}}','result structure'),
])
def test_malformed_response(monkeypatch,stdout,message):
    monkeypatch.setattr(client.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=stdout,stderr='',returncode=0))
    with pytest.raises(RuntimeError,match=message): client.analyze(benchmark(),sys.executable)

def test_worker_nonzero_exit(monkeypatch):
    monkeypatch.setattr(client.subprocess,'run',lambda *a,**k:SimpleNamespace(stdout=json.dumps({'protocol':1,'ok':True,'result':{'cases':{}}}),stderr='worker crashed',returncode=1))
    with pytest.raises(RuntimeError,match='exited unexpectedly'): client.analyze(benchmark(),sys.executable)

def test_worker_unicode_stderr(monkeypatch,tmp_path):
    script=tmp_path/'worker.py'
    script.write_text("import sys\nsys.stderr.buffer.write(b'\\x81\\xff')\nprint('{\"protocol\":1,\"ok\":false,\"error\":\"unstable\"}')\n",encoding='utf-8')
    monkeypatch.setattr(client,'__file__',str(tmp_path/'client.py'))
    with pytest.raises(RuntimeError,match='unstable'):
        client.analyze(benchmark(),sys.executable)
