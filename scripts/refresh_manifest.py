from pathlib import Path
import hashlib,json
root=Path(__file__).resolve().parents[1]/'portable'
files={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file() and p.name not in ('manifest.json','installed.json') and not any(x in p.parts for x in ('__pycache__','personal-backup','data','.git')) and p.suffix!='.pyc'}
(root/'manifest.json').write_text(json.dumps({'version':'public-2026.10.09','files':files},ensure_ascii=False,indent=2)+'\n',encoding='utf8')
print(f'Manifest: {len(files)} files')
