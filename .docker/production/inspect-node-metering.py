"""List bounded deployment metadata locations, never file contents or credentials."""
import json
import ast
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
