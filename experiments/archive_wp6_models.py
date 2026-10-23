"""Losslessly archive completed WP6 mutant copies after full verification.

Source/reference projects and active runs are never eligible. Every archive is
roundtripped by SHA-256 before any original file is unlinked. A discovery marker
remains inside the former project directory. ZIP bytes retain every original file.
"""
from __future__ import annotations
import argparse,hashlib,json,zipfile
from pathlib import Path


def sha(path):
 h=hashlib.sha256()
 with Path(path).open('rb') as f:
  for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
 return h.hexdigest()


def inside(path,parent):
 resolved=path.resolve();base=parent.resolve()
 if resolved==base or not resolved.is_relative_to(base):raise ValueError('Path escapes intended model directory: '+str(path))
 return resolved


def verify_archive(path,entries):
 with zipfile.ZipFile(path) as archive:
  if set(archive.namelist())!=set(entries) or len(archive.namelist())!=len(entries):raise ValueError('ZIP entry inventory mismatch')
  for name,meta in entries.items():
   h=hashlib.sha256();size=0
   with archive.open(name) as f:
    for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk);size+=len(chunk)
   if h.hexdigest()!=meta['sha256'] or size!=meta['bytes']:raise ValueError('ZIP roundtrip mismatch: '+name)


def archive_run(run):
 run=Path(run).resolve();summary=json.loads((run/'summary.json').read_text(encoding='utf-8'))
 if not summary.get('evaluation_complete') or summary.get('worker_failures'):raise ValueError('Only a fully completed run without worker failures can be archived')
 manifest=json.loads((run/'mutation_manifest.json').read_text(encoding='utf-8'));model_root=(run/'models').resolve();archive_root=run/'archives';archive_root.mkdir(exist_ok=True)
 outcomes={p.stem for p in (run/'outcomes').glob('*.json')};results=[]
 for item in manifest['models']:
  if item['status'] not in {'changed','incomplete'}:continue
  sid=item['storage_id']
  if sid not in outcomes:raise ValueError('No completed outcome for '+sid)
  directory=inside(model_root/sid,model_root)
  markers=list(directory.glob('*/ARCHIVED_MODEL.json'))
  if markers:
   results.append({'storage_id':sid,'status':'already_archived'});continue
  projects=[p for p in directory.iterdir() if p.is_dir()]
  if len(projects)!=1:raise ValueError('Expected exactly one copied project: '+str(directory))
  project=inside(projects[0],directory);files=sorted(p for p in project.rglob('*') if p.is_file())
  if any(p.is_symlink() for p in project.rglob('*')):raise ValueError('Symlink is not eligible for archive')
  entries={str(inside(p,project).relative_to(directory)).replace('\\','/'):{'sha256':sha(p),'bytes':p.stat().st_size,'kind':'file'} for p in files}
  directories=sorted(p for p in project.rglob('*') if p.is_dir())
  for p in directories:entries[str(inside(p,project).relative_to(directory)).replace('\\','/')+'/']={'sha256':hashlib.sha256(b'').hexdigest(),'bytes':0,'kind':'directory'}
  destination=archive_root/(sid+'.zip');temporary=archive_root/(sid+'.zip.pending');index_path=archive_root/(sid+'.manifest.json')
  if destination.exists() or temporary.exists() or index_path.exists():raise FileExistsError('Archive output already exists; inspect rather than overwrite: '+sid)
  with zipfile.ZipFile(temporary,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6,allowZip64=True) as archive:
   for p in files:archive.write(p,str(p.relative_to(directory)).replace('\\','/'))
   for p in directories:archive.write(p,str(p.relative_to(directory)).replace('\\','/')+'/')
  verify_archive(temporary,entries)
  for p in files:
   name=str(p.relative_to(directory)).replace('\\','/')
   if sha(p)!=entries[name]['sha256']:raise ValueError('Original changed after ZIP roundtrip: '+name)
  temporary.rename(destination)
  index={'model_id':item['id'],'storage_id':sid,'archive':str(destination.relative_to(run)).replace('\\','/'),'archive_sha256':sha(destination),'project_directory':str(project.relative_to(run)).replace('\\','/'),'entries':entries,'condition':'completed mutant copies only; every ZIP entry SHA-256 roundtripped before originals removed'}
  index_path.write_text(json.dumps(index,indent=2,sort_keys=True)+'\n',encoding='utf-8')
  marker=project/'ARCHIVED_MODEL.json';marker.write_text(json.dumps({'archive_manifest':str(index_path.relative_to(run)).replace('\\','/'),'archive_sha256':index['archive_sha256'],'original_project_files':sum(x.get('kind')=='file' for x in entries.values()),'original_directory_entries':sum(x.get('kind')=='directory' for x in entries.values()),'restore_command':'python experiments/archive_wp6_models.py --run-dir '+str(run)+' --restore '+sid},indent=2)+'\n',encoding='utf-8')
  # Enumerated files only; no recursive deletion or computed cross-shell command.
  for p in files:inside(p,project).unlink()
  for p in sorted((p for p in project.rglob('*') if p.is_dir()),key=lambda p:len(p.parts),reverse=True):inside(p,project).rmdir()
  results.append({'storage_id':sid,'status':'archived','original_bytes':sum(x['bytes'] for x in entries.values()),'archive_bytes':destination.stat().st_size,'file_count':sum(x.get('kind')=='file' for x in entries.values()),'directory_count':sum(x.get('kind')=='directory' for x in entries.values())})
 return results


def restore(run,sid):
 run=Path(run).resolve();index_path=inside(run/'archives'/(sid+'.manifest.json'),run/'archives');index=json.loads(index_path.read_text());archive=inside(run/index['archive'],run);project=inside(run/index['project_directory'],run/'models');directory=project.parent
 if sha(archive)!=index['archive_sha256']:raise ValueError('Archive SHA-256 mismatch')
 verify_archive(archive,index['entries'])
 with zipfile.ZipFile(archive) as z:
  for name,meta in index['entries'].items():
   target=inside(directory/name,project)
   if meta.get('kind')=='directory':target.mkdir(parents=True,exist_ok=True);continue
   target.parent.mkdir(parents=True,exist_ok=True)
   if target.exists():
    if sha(target)!=meta['sha256']:raise ValueError('Restore would overwrite differing bytes')
   else:
    with target.open('xb') as f,z.open(name) as source:
     for chunk in iter(lambda:source.read(1024*1024),b''):f.write(chunk)
   if sha(target)!=meta['sha256']:raise ValueError('Restored byte mismatch')
 return {'storage_id':sid,'restored_files':sum(x.get('kind')=='file' for x in index['entries'].values()),'restored_directories':sum(x.get('kind')=='directory' for x in index['entries'].values()),'archive_retained':True}


def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--restore');a=p.parse_args();result=restore(a.run_dir,a.restore) if a.restore else archive_run(a.run_dir);print(json.dumps(result,indent=2))
if __name__=='__main__':main()
