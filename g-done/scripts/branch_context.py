#!/usr/bin/env python3
"""每个 change 的分支约定；读侧供 gate/suite-scope 共用，写侧只记录明确选择。"""
import argparse
import json
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try: _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception: pass

CONTEXT_FILE = ".g-branch.json"
FIELDS = {"source_branch", "work_branch", "base_sha", "merge_target"}


def _gate():
    import ship_gate
    return ship_gate


def validate(root, data):
    sg = _gate()
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError("分支约定须含 source_branch/work_branch/base_sha/merge_target 四个字段")
    for field in ("source_branch", "work_branch", "merge_target"):
        name = data[field]
        if field == "merge_target" and name is None:
            continue
        if not isinstance(name, str) or not name or name.startswith("-") or name == "HEAD" or sg.run_git_rc(root, "check-ref-format", f"refs/heads/{name}")[0]:
            raise ValueError(f"分支约定 {field} 不是合法分支名")
    sha = data["base_sha"]
    if not sg._is_full_oid(sha) or sg.run_git_rc(root, "cat-file", "-e", f"{sha}^{{commit}}")[0]:
        raise ValueError("分支约定 base_sha 必须是已存在的完整起始提交 OID")
    if data["merge_target"] == data["work_branch"]:
        raise ValueError("merge_target 不得是工作分支自身；原地完成用 null")
    return data


def read(root, directory, ref=None):
    sg = _gate()
    # 旧变更不改历史文件；新写入使用 G 名称。
    for filename in (CONTEXT_FILE, ".sdflow-branch.json"):
        path = directory / filename
        if ref is None:
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
        else:
            rc, text = sg.run_git_rc(root, "show", f"{ref}:{path.relative_to(root).as_posix()}")
            if rc:
                entries = sg.ls_tree_map(root, ref, [path.relative_to(root).as_posix()])
                if entries:
                    raise ValueError("无法读取已提交的分支约定")
                continue
        return validate(root, json.loads(text))
    return None


def locate(root, change):
    if not change or change in (".", "..") or "/" in change or "\\" in change:
        raise ValueError("change 必须是单一目录名")
    directory = root / "openspec/changes" / change
    if directory.is_dir():
        try:
            directory.resolve().relative_to((root / "openspec/changes").resolve())
        except ValueError:
            raise ValueError("change 目录逃逸")
        return directory, None
    # 〔A2〕已 `openspec archive`、归档尚未提交：约定文件只在工作树里（与 ship_gate 同口径、同优先级）。
    pending = _gate().uncommitted_archive_dirs(root, change)
    if len(pending) == 1:
        return root / "openspec/changes/archive" / pending[0], None
    if len(pending) > 1:
        raise ValueError("工作树里有多个未提交的归档目录，无法唯一定位本 change")
    dirs = _gate().archived_dirs_in_tree(root, "HEAD", change)
    if len(dirs) != 1:
        raise ValueError("无法唯一定位当前 HEAD 中的归档 change（active 目录也不在：若刚切走工作分支，"
                         "先 git checkout 回本 change 的 work_branch）")
    return root / "openspec/changes/archive" / next(iter(dirs)), "HEAD"


def get(root, change):
    directory, ref = locate(root, change)
    data = read(root, directory, ref)
    if data is None:
        raise ValueError("缺少 .g-branch.json；先确认原始起点与工作方式并补录，禁止猜默认分支")
    return directory, data


def target_ref(root, name):
    if name is None:
        return None
    sg = _gate()
    for ref in (f"refs/heads/{name}", f"refs/remotes/origin/{name}"):
        if sg.run_git_rc(root, "rev-parse", "--verify", ref)[0] == 0:
            return ref
    raise ValueError(f"合并目标分支 {name!r} 不存在，禁止回退默认分支")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("action", choices=("init", "show", "set-target"))
    p.add_argument("--root", default=".")
    p.add_argument("--change", required=True)
    p.add_argument("--source", help="切分支前记录的起始分支名")
    p.add_argument("--base", help="切分支前记录的完整提交 OID")
    p.add_argument("--target", help="仅用户明确指定其它合并目标时使用")
    a = p.parse_args(argv)
    root = Path(a.root).resolve()
    sg = _gate()
    try:
        directory, ref = locate(root, a.change)
        old = read(root, directory, ref)
        current = sg.run_git(root, "symbolic-ref", "--quiet", "--short", "HEAD")
        if a.action == "show":
            _, data = get(root, a.change)
        elif a.action == "init":
            work = current
            data = validate(root, dict(source_branch=a.source, work_branch=work,
                                       base_sha=a.base, merge_target=None))
            if a.target is not None:
                data["merge_target"] = None if a.target == work else a.target
                validate(root, data)
            if old is not None and old != data:
                raise ValueError("已有分支约定不同，拒绝重初始化覆盖起始身份")
            if sg.run_git_rc(root, "merge-base", "--is-ancestor", data["base_sha"], "HEAD")[0]:
                raise ValueError("起始提交不是当前工作分支祖先")
        else:
            _, data = get(root, a.change)
            if current != data["work_branch"]:
                raise ValueError("修改合并目标须在记录的工作分支上执行")
            if a.target is None:
                raise ValueError("set-target 必须显式提供 --target")
            data["merge_target"] = None if a.target == data["work_branch"] else a.target
            validate(root, data)
        if a.action != "show":
            target_ref(root, data["merge_target"])
            path = directory / CONTEXT_FILE
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            tmp.replace(path)
        print(json.dumps(dict(data, context_path=(directory / CONTEXT_FILE).relative_to(root).as_posix()), ensure_ascii=False))
        return 0
    except (ValueError, OSError, sg.GateIndeterminate) as exc:
        print(f"分支约定失败：{exc}", file=sys.stderr)
        return 6


if __name__ == "__main__":
    raise SystemExit(main())
