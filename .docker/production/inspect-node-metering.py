"""List bounded deployment metadata locations, never file contents or credentials."""
import json
import ast
import subprocess
from pathlib import Path

roots = [
    Path('/root/Xboard/backups/fleet-20261017'),
    Path('/root/Xboard/backups/hk-mesh-20261017'),
    Path('/root/Xboard/backups/upstream-20261022'),
    Path('/root/Xboard/backups/friendhosting-jp-20261021'),
    Path('/root/Xboard/backups/friendhosting-nl-20261021'),
    Path('/root/Xboard/backups/friendhosting-ro-20261021'),
]
print(json.dumps([{'directory': str(root), 'exists': root.is_dir(),
                   'files': [{'name': f.name, 'directory': f.is_dir()}
                             for f in sorted(root.iterdir())[:60]] if root.is_dir() else []}
                  for root in roots]))

def shape(value, depth=0):
    if depth > 3:
        return type(value).__name__
    if isinstance(value, dict):
        return {str(key): shape(item, depth + 1) for key, item in list(value.items())[:35]}
    if isinstance(value, list):
        return [shape(item, depth + 1) for item in value[:2]]
    return type(value).__name__

for root in roots[:2]:
    for name in ('manifest.json', 'extra-manifest.json', 'ready.json'):
        path = root / name
        if path.is_file():
            print(json.dumps({'path': str(path), 'schema': shape(json.loads(path.read_text()))}))
    for name in ('fleet.py', 'deploy.py'):
        path = root / name
        if path.is_file():
            tree = ast.parse(path.read_text())
            print(json.dumps({'path': str(path), 'functions': [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)],
                              'imports': [ast.unparse(n) for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))]}))
            class RedactConstants(ast.NodeTransformer):
                def visit_Constant(self, node):
                    if isinstance(node.value, str):
                        return ast.Constant(value='<string>')
                    return node
            for node in tree.body:
                if isinstance(node, ast.Assign) or (isinstance(node, ast.FunctionDef) and node.name == 'conn'):
                    print(json.dumps({'code_shape': ast.unparse(RedactConstants().visit(node))}))

containers = subprocess.check_output(['docker', 'ps', '--format', '{{.ID}} {{.Names}}'], text=True)
for line in containers.splitlines():
    cid, name = line.split(' ', 1)
    if 'xboard' not in name.lower():
        continue
    meta = json.loads(subprocess.check_output(['docker', 'inspect', cid], text=True))[0]
    for mount in meta['Mounts']:
        if mount['Destination'] != '/www/storage':
            continue
        root = Path(mount['Source']) / 'app/backups'
        for tag in ('friendhosting-jp-20261021', 'friendhosting-nl-20261021', 'friendhosting-ro-20261021'):
            folder = root / tag
            print(json.dumps({'backup': str(folder), 'files': [f.name for f in folder.iterdir()] if folder.is_dir() else []}))
