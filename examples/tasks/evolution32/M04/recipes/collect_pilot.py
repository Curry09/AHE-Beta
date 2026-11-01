"""Package existing pilot outputs after Actor freeze; never generate a solution."""

from pathlib import Path
import hashlib
import io
import json
import os
import stat
import tarfile
import tempfile


root = Path('/app/repo')
reports = root/'reports'
pilot = reports/'pilot'
target = reports/'.collected-pilot.tar.gz'
invalid = []
files = []
total = 0
blocked_target = False
if reports.is_dir() and not reports.is_symlink():
    try:
        existing = target.lstat()
    except FileNotFoundError:
        pass
    else:
        if stat.S_ISREG(existing.st_mode) or stat.S_ISLNK(existing.st_mode):
            target.unlink()
        else:
            blocked_target = True
if blocked_target or reports.is_symlink() or pilot.is_symlink() or not pilot.is_dir():
    print(json.dumps({'pilot_collection': 'missing_or_invalid_task_output'}))
else:
    for path in sorted(pilot.rglob('*')):
        value = path.lstat()
        if stat.S_ISDIR(value.st_mode):
            continue
        if not stat.S_ISREG(value.st_mode):
            invalid.append(str(path.relative_to(pilot)))
            continue
        total += value.st_size
        if value.st_size > 8*1024**2 or total > 32*1024**2 or len(files) >= 1000:
            invalid.append('task_output_exceeds_capture_limit')
            break
        files.append(path)
    if invalid or not files:
        print(json.dumps({'pilot_collection': 'invalid_or_empty_task_output', 'details': invalid}))
    else:
        manifest = {str(p.relative_to(pilot)): {
            'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
        } for p in files}
        fd, temporary = tempfile.mkstemp(prefix='m04-pilot-', suffix='.tar.gz')
        os.close(fd)
        try:
            with tarfile.open(temporary, 'w:gz', dereference=True) as archive:
                for path in files:
                    archive.add(path, arcname='pilot/'+str(path.relative_to(pilot)), recursive=False)
                data = (json.dumps({'actor_outputs': manifest}, indent=2)+'\n').encode()
                entry = tarfile.TarInfo('collection-manifest.json')
                entry.size = len(data)
                entry.mode = 0o644
                archive.addfile(entry, io.BytesIO(data))
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        print(json.dumps({'pilot_collection': 'packaged_existing_outputs', 'files': len(files),
                          'uncompressed_bytes': total}))
