"""Workspace lifecycle and explicit local export destination integration tests."""
import errno
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from PIL import Image

from ai_text_sharpener.studio import create_server
from ai_text_sharpener.studio_files import directory_contents, export_destination, save_export


@pytest.fixture
def server(tmp_path):
    server = create_server(tmp_path/'data', 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown();server.server_close();thread.join();server.app.executor.shutdown()


def post(server, path, data, authenticated=True):
    headers={'Content-Type':'application/json'}
    if authenticated:headers['X-Studio-Token']=server.app.token
    request=urllib.request.Request(f'http://127.0.0.1:{server.server_port}'+path,
                                   data=json.dumps(data).encode(),headers=headers)
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def make_project(server):
    p=server.app.store.create('测试工作区')
    server.app.store.add_images(p,[('first',Image.new('RGB',(60,40),'red')),
                                    ('second',Image.new('RGB',(60,40),'blue'))])
    return p


def test_trash_restore_and_stale_save_cannot_resurrect(server):
    p=make_project(server)
    directory=server.app.store.directory(p['id'])
    contents={f.name:f.read_bytes() for f in directory.iterdir()}
    with pytest.raises(urllib.error.HTTPError) as error:
        post(server,'/api/workspace/trash',dict(id=p['id'],revision=p['revision']-1))
    assert error.value.code==409 and directory.exists()
    post(server,'/api/workspace/trash',dict(id=p['id'],revision=p['revision']))
    listing=post(server,'/api/workspaces',{})
    assert listing['projects']==[] and listing['trash'][0]['id']==p['id']
    assert not directory.exists()
    with pytest.raises(urllib.error.HTTPError):post(server,'/api/save',p)
    assert not directory.exists()
    post(server,'/api/workspace/restore',dict(id=p['id']))
    assert {f.name:f.read_bytes() for f in directory.iterdir()}==contents
    assert post(server,'/api/workspaces',{})['trash']==[]


@pytest.mark.parametrize('path,data', [('/api/workspace/trash',{}),('/api/workspace/restore',{}),
                                      ('/api/workspaces',{}),('/api/folders',{'path':'/'})])
def test_file_management_requires_session_token(server,path,data):
    with pytest.raises(urllib.error.HTTPError) as error:post(server,path,data,False)
    assert error.value.code==403


def test_delete_is_blocked_while_processing_and_ids_are_validated(server):
    p=make_project(server)
    server.app.job['active']=True
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            post(server,'/api/workspace/trash',dict(id=p['id'],revision=p['revision']))
        assert error.value.code==409
    finally:server.app.job['active']=False
    with pytest.raises(urllib.error.HTTPError) as error:
        post(server,'/api/workspace/restore',dict(id='../outside'))
    assert error.value.code==400
    assert server.app.store.directory(p['id']).exists()


@pytest.mark.parametrize('scope,format,extension', [('all','pptx','pptx'),('current','pptx','pptx'),
    ('all','svg','zip'),('current','svg','svg'),('all','png','zip'),('current','png','png'),('all','json','json')])
def test_export_to_chosen_directory_preserves_existing_file(server,tmp_path,scope,format,extension):
    p=make_project(server);output=tmp_path/'导出结果';output.mkdir()
    name=f'我的结果.{extension}';existing=output/name;existing.write_bytes(b'do not overwrite')
    job=post(server,'/api/job',dict(kind='export',project_id=p['id'],revision=p['revision'],
        page_id=p['pages'][1]['id'],scope=scope,format=format,destination={'directory':str(output),'filename':name}))
    server.app.executor.submit(lambda:None).result(timeout=20)
    result=server.app.job
    assert result['status']=='done',result
    assert result['download'] is None
    saved=Path(result['saved_path'])
    assert saved==output/f'我的结果 (1).{extension}'
    assert saved.stat().st_size>0 and existing.read_bytes()==b'do not overwrite'
    assert not list(output.glob('*.tmp'))
    preferences=json.loads((server.app.store.root/'preferences.json').read_text())
    assert preferences['export_directory']==str(output)
    if format=='json':
        assert json.loads(saved.read_text())==p
        assert all(page['render_revision']==-1 for page in server.app.store.load(p['id'])['pages'])


@pytest.mark.parametrize('name',['','../outside.pptx','a/b.pptx','x.png','x\x00.pptx'])
def test_export_filename_validation(tmp_path,name):
    with pytest.raises(ValueError):
        export_destination({'directory':str(tmp_path),'filename':name},'pptx',tmp_path/'data')


def test_directory_selection_and_protection(tmp_path):
    for name in ['B','a','文件夹','.hidden']:(tmp_path/name).mkdir()
    (tmp_path/'file.txt').write_text('test')
    listing=directory_contents(str(tmp_path))
    assert listing['folders']==['a','B','文件夹'] and listing['path']==str(tmp_path)
    root=tmp_path/'data';root.mkdir()
    alias=tmp_path/'alias';alias.symlink_to(root,target_is_directory=True)
    for path in [root,alias,Path('relative')]:
        with pytest.raises(ValueError):export_destination({'directory':str(path),'filename':'x.pptx'},'pptx',root)


def test_save_on_filesystem_without_hardlinks_and_cancel(tmp_path,monkeypatch):
    source=tmp_path/'source';source.write_bytes(b'result')
    dest=tmp_path/'out.pptx';dest.write_bytes(b'original')
    def unsupported(*args):raise OSError(errno.EOPNOTSUPP,'hardlinks unavailable')
    monkeypatch.setattr('ai_text_sharpener.studio_files.os.link',unsupported)
    saved=save_export(source,dest)
    assert saved.name=='out (1).pptx' and saved.read_bytes()==b'result'
    assert dest.read_bytes()==b'original'
    def cancel(*args):raise InterruptedError()
    with pytest.raises(InterruptedError):save_export(source,tmp_path/'cancelled.pptx',cancel)
    assert not (tmp_path/'cancelled.pptx').exists()
    assert not list(tmp_path.glob('.sharpener-*'))


def test_permission_failure_reports_error_without_changing_project(server,tmp_path,monkeypatch):
    p=make_project(server)
    def denied(*args,**kwargs):raise PermissionError('read-only folder')
    monkeypatch.setattr('ai_text_sharpener.studio.save_export',denied)
    post(server,'/api/job',dict(kind='export',project_id=p['id'],revision=p['revision'],
        destination={'directory':str(tmp_path),'filename':'output.pptx'}))
    server.app.executor.submit(lambda:None).result(timeout=20)
    assert server.app.job['status']=='error' and '权限' in server.app.job['message']
    assert server.app.store.load(p['id'])==p
    assert not (tmp_path/'output.pptx').exists()
