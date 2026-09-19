"""Install optional CPU formula components without altering Studio's environment.

Run with Python 3.11/3.12: .venv/bin/python scripts/install-formulas.py [--node PATH]
Downloads ~260 MB of models plus MathJax and a separate Python environment.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import urllib.request

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('XDG_DATA_HOME',str(Path.home()/'.local/share')))/'ai-text-sharpener/formula'
MODELS={
 'mfd.onnx':('https://huggingface.co/breezedeus/pix2text-mfd-1.5/resolve/f470a885e0fca1d3d2bfa2a54991db7ae01f1861/pix2text-mfd-1.5.onnx','40d4fc852d99bcbf25a9478897d2f49fbbb8f7fdd6569c088cd1c31386293bd7'),
 'encoder.onnx':('https://github.com/RapidAI/RapidLaTeXOCR/releases/download/v0.0.0/encoder.onnx','01bf5dc25539ca0cd5b1bd29296ea495977a6ba5f629dc4178277809d26e5e7d'),
 'decoder.onnx':('https://github.com/RapidAI/RapidLaTeXOCR/releases/download/v0.0.0/decoder.onnx','bd695497bf1b22279b7626f5916c79226e1e244c84355f8da7edfd2d921d0072'),
 'image_resizer.onnx':('https://github.com/RapidAI/RapidLaTeXOCR/releases/download/v0.0.0/image_resizer.onnx','e0b075c39700f64d50400f39c8fc186bbb3b5d84d31864008313f376603aca9d'),
 'tokenizer.json':('https://github.com/RapidAI/RapidLaTeXOCR/releases/download/v0.0.0/tokenizer.json','1dc27b18d6a518d0d5ff3f4bb7bd98521fe80ad39e5b2a246d4109f1bb9d5019'),
 'mathjax.tgz':('https://registry.npmjs.org/mathjax-full/-/mathjax-full-3.2.2.tgz','d8f080d2e4bdfb75284aac34d5eff155002eca47798b1d4e4bde31453e653f87'),
}

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--node');args=parser.parse_args()
    if sys.version_info[:2] not in {(3,11),(3,12)}:
        raise SystemExit('请使用 Studio 的 .venv/bin/python（Python 3.11 / 3.12）。')
    node=args.node or shutil.which('node')
    if not node:
        candidates=list((Path.home()/'.cache/codex-runtimes').glob('*/dependencies/node/bin/node'))
        node=str(candidates[0]) if candidates else None
    if not node or not Path(node).is_file():raise SystemExit('未找到 Node.js。请安装 Node.js 18+，或通过 --node 指定可执行文件。')
    subprocess.run([node,'--version'],check=True)
    DATA.mkdir(parents=True,exist_ok=True)
    for name,(url,sha) in MODELS.items():
        dest=DATA/name
        if dest.is_file() and digest(dest)==sha:continue
        print('下载',name,flush=True);temp=dest.with_suffix(dest.suffix+'.tmp')
        try:
            with urllib.request.urlopen(url,timeout=60) as r,temp.open('wb') as f:shutil.copyfileobj(r,f)
            if digest(temp)!=sha:raise RuntimeError(f'{name} 校验失败，未启用下载文件。')
            temp.replace(dest)
        finally:temp.unlink(missing_ok=True)
    with tarfile.open(DATA/'mathjax.tgz') as t:t.extractall(DATA/'mathjax',filter='data')
    env=ROOT/'.venv-formula'
    if not (env/'bin/python').is_file():subprocess.run([sys.executable,'-m','venv',str(env)],check=True)
    subprocess.run([str(env/'bin/python'),'-m','pip','install','-r',str(ROOT/'requirements-formula.lock.txt')],check=True)
    # Preserve the installed local executable if a Codex runtime cache is cleaned.
    target=DATA/'node'
    if Path(node).resolve()!=target.resolve():shutil.copy2(node,target)
    (DATA/'runtime.json').write_text(json.dumps({'node':str(target),'python':str(env/'bin/python')},indent=2))
    (DATA/'sources.json').write_text(json.dumps(MODELS,indent=2))
    print('公式组件安装完成；重启文字重绘服务后生效。')

if __name__=='__main__':main()
