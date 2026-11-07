"""List bounded deployment metadata locations, never file contents or credentials."""
import json
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
