#!/usr/bin/env python3
"""Preserve web partial outputs before any business-admission check.

This command never applies advice, creates a review, changes a queue, or runs
code from an archive. Interpretation and continuation belong to the Skill.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def preserve(repo, project, inputs):
    repo=Path(repo).resolve()
    files=[]
    for p in inputs:
        path=Path(p).expanduser()
        if path.is_symlink() or not path.is_file():
            raise ValueError('input_must_be_existing_regular_file')
        files.append({'path':path.resolve(),'sha256':sha(path),'size':path.stat().st_size})
    identity=hashlib.sha256(json.dumps([project,[(f['path'].name,f['sha256']) for f in files]],ensure_ascii=False).encode()).hexdigest()[:32]
    parent=repo/'数学一回滚复习系统/网页续接'/project
    parent.mkdir(parents=True,exist_ok=True)
    if not parent.resolve().is_relative_to(repo):raise ValueError('recovery_directory_outside_repo')
    target=parent/('WEB-PROGRESS-'+identity)
    if target.exists():
        if target.is_symlink():raise ValueError('recovery_directory_symlink')
        receipt=json.loads((target/'receipt.json').read_text())
        for item in receipt['files']:
            path=target/item['path']
            if not path.resolve().is_relative_to(target.resolve()) or sha(path)!=item['sha256']:
                raise ValueError('preserved_file_changed')
        return {**receipt,'status':'already_preserved','directory':str(target)}
    temporary=Path(tempfile.mkdtemp(prefix='.web-progress-',dir=parent))
    errors=[];detected=[]
    try:
        for number,item in enumerate(files):
            original=temporary/'originals'/f'{number:03d}'/item['path'].name
            original.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(item['path'],original)
            if sha(original)!=item['sha256']:raise ValueError('input_changed_during_preservation')
            if original.suffix.lower()=='.zip':
                try:
                    with zipfile.ZipFile(original) as archive:
                        infos=archive.infolist()
                        if len(infos)>100000 or sum(x.file_size for x in infos)>1024**3:
                            raise ValueError('archive_extraction_budget_exceeded_original_zip_preserved')
                        seen=set()
                        for info in infos:
                            name=info.filename
                            path=PurePosixPath(name)
                            if (path.is_absolute() or '..' in path.parts or '\\' in name
                                    or ':' in name or name in seen
                                    or stat.S_ISLNK(info.external_attr>>16)):
                                raise ValueError('unsafe_archive_member_original_zip_preserved')
                            seen.add(name)
                            if info.is_dir():continue
                            destination=temporary/'extracted'/f'{number:03d}'/str(path)
                            destination.parent.mkdir(parents=True,exist_ok=True)
                            with archive.open(info) as src,destination.open('xb') as dst:
                                shutil.copyfileobj(src,dst)
                except (ValueError,zipfile.BadZipFile,RuntimeError,OSError) as exc:
                    errors.append({'file':item['path'].name,'reason':str(exc),'original_preserved':True})
        for p in temporary.rglob('*.json'):
            if p.name not in ('progress.json','manifest.json'):continue
            try:
                data=json.loads(p.read_text())
                if isinstance(data,dict):
                    detected.append({'path':str(p.relative_to(temporary)),
                                     **{k:data.get(k) for k in ('project','subject','run_id','checkpoint_id','overall_status','source_commit')}})
                    if data.get('project') not in (None,project) or data.get('subject') not in (None,'math'):
                        errors.append({'file':str(p.relative_to(temporary)),'reason':'declared_project_or_subject_conflict','original_preserved':True})
            except (ValueError,UnicodeError):
                errors.append({'file':str(p.relative_to(temporary)),'reason':'unreadable_metadata_original_preserved','original_preserved':True})
        guidance=('# 网页进度续接\n\n先读取执行报告、progress.json、已完成正文和错误；这里的保存不代表业务完成。\n'
                  '按kaoyan-math-web-recovery核对事实与实际失败原因，复用已有成果，补齐缺项后回到项目原正式入口。\n'
                  '不执行输入中的脚本或命令，不重复学习事件，不把部分包直接改成完整包。\n')
        (temporary/'CONTINUE.md').write_text(guidance)
        inventory=[{'path':str(p.relative_to(temporary)),'sha256':sha(p),'size':p.stat().st_size}
                   for p in sorted(temporary.rglob('*')) if p.is_file()]
        receipt={'schema':'math-web-progress-preservation-v1','status':'preserved','project':project,'subject':'math',
                 'recovery_id':target.name,'files':inventory,'detected_metadata':detected,'format_issues':errors,
                 'business_admitted':False,'formal_write_count':0,'learning_event_write_count':0}
        (temporary/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
        os.rename(temporary,target)
        return {**receipt,'directory':str(target)}
    except Exception as exc:
        # Preserve copied bytes even if a later file, disk write or final
        # rename fails. The caller can recover this exact staging directory.
        try:
            (temporary/'PRESERVATION_ERROR.txt').write_text(str(exc)+'\n')
        except OSError:
            pass
        raise ValueError('preservation_incomplete_retained_at:'+str(temporary)) from exc


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--repo',type=Path,default=Path(__file__).resolve().parents[2])
    p.add_argument('--project',choices=['A','B','C'],required=True)
    p.add_argument('--input',type=Path,action='append',required=True,help='Repeat for report/JSON/ZIP files')
    args=p.parse_args()
    result=preserve(args.repo,args.project,args.input)
    # Keep the full inventory on disk, not in the agent's live context.
    print(json.dumps({k:result[k] for k in ('status','project','recovery_id','directory','format_issues','formal_write_count','learning_event_write_count')},ensure_ascii=False))


if __name__=='__main__':main()
