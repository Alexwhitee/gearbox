"""
Tests for init.py's bundle deployment, retired-file/hook cleanup, and hook installer.
Run with: python3 -m pytest g-init/tests/test_init.py -v
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))
import init as init_mod
from init import copy_bundle, retire_deploy_files


class TestRetireDeployFiles:
    """drop-review-html-viewer：曾铺进消费仓 openspec/ 根的查看器根锚（serve.sh + review.html）
    在 init/update 每次运行时被**签名门控删除**；用户自建同名文件（无 bundle 签名）不被误删；
    fresh 安装（无残留）则 no-op。与 retire_hooks 同构。"""

    def _write(self, root, rel, content):
        osroot = root / "openspec"
        osroot.mkdir(parents=True, exist_ok=True)
        p = osroot / rel
        p.write_text(content, encoding="utf-8")
        return p

    def test_removes_deployed_viewer_anchors(self, tmp_path):
        # 复刻 bundle 部署签名：review.html 含渲染 token 的宿主变量名、serve.sh 含 PIDFILE key 前缀
        review = self._write(tmp_path, "review.html",
                             '<script>window.__OPENSPEC_PROJECT_NAME__ = "x";</script>')
        serve = self._write(tmp_path, "serve.sh",
                            'PIDFILE="/tmp/openspec-review-serve-${KEY}.pid"\n')
        acts = retire_deploy_files(str(tmp_path))
        assert not review.exists()
        assert not serve.exists()
        assert "review.html" in acts and "serve.sh" in acts

    def test_skips_user_files_without_signature(self, tmp_path):
        # 用户自建同名文件，内容不含 bundle 签名 → MUST NOT 删
        review = self._write(tmp_path, "review.html", "# my own notes about a review\n")
        serve = self._write(tmp_path, "serve.sh", "#!/bin/sh\necho my own server\n")
        acts = retire_deploy_files(str(tmp_path))
        assert review.exists() and serve.exists()
        assert acts.strip() == "· 无退役部署文件残留"

    def test_noop_on_fresh_install(self, tmp_path):
        (tmp_path / "openspec").mkdir()
        acts = retire_deploy_files(str(tmp_path))
        assert acts.strip() == "· 无退役部署文件残留"

    def test_idempotent(self, tmp_path):
        self._write(tmp_path, "review.html",
                    '<script>window.__OPENSPEC_PROJECT_NAME__ = "x";</script>')
        retire_deploy_files(str(tmp_path))
        acts2 = retire_deploy_files(str(tmp_path))   # 第二次跑：已删净 → no-op
        assert acts2.strip() == "· 无退役部署文件残留"

    def test_run_retires_deployed_viewer(self, tmp_path, monkeypatch):
        # 端到端：run(update) 应清掉已铺的查看器根锚
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fake-claude"))
        proj = tmp_path / "proj"
        (proj / "openspec").mkdir(parents=True)
        (proj / "openspec" / "review.html").write_text(
            '<script>window.__OPENSPEC_PROJECT_NAME__ = "x";</script>', encoding="utf-8")
        (proj / "openspec" / "serve.sh").write_text(
            'PIDFILE="/tmp/openspec-review-serve-${KEY}.pid"\n', encoding="utf-8")
        init_mod.run(str(proj), "update")
        assert not (proj / "openspec" / "review.html").exists()
        assert not (proj / "openspec" / "serve.sh").exists()


class TestNoConsumerHack:
    """checkpoint 全局化（~/.g/hack/，由 setup.sh 安装）：init/update 不再往消费仓铺 hack/。"""

    def test_init_module_has_no_copy_hack(self):
        assert not hasattr(init_mod, "copy_hack")

    def test_run_does_not_create_consumer_hack_dir(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fake-claude"))
        init_mod.run(str(tmp_path / "proj"), "init")
        assert not (tmp_path / "proj" / "hack").exists()


class TestBundleGuideAndSchemaOnly:
    """fix-probe-scan-precision R2/R3：copy_bundle 只铺 WORKFLOW-GUIDE.md（人读手册）+
    project-local schema。规则本体、`tools/`、`lens-metric-contract.md` 全部经全局 canonical
    解析（resolve-workflow.sh 两步链），MUST NOT 复制进消费仓——`--dev`/`full=True` 整 bundle
    刷新与 tools/ 子树部署（原 R-MRF-1）已随此次收缩退役。"""

    def test_deploys_only_guide(self, tmp_path):
        dst, n = copy_bundle(str(tmp_path), include_schema=False)
        wf = tmp_path / "openspec" / "workflow"
        # 文件全集断言（非"包含"断言）：openspec/workflow/ 下只有 WORKFLOW-GUIDE.md 一个文件
        all_files = {p.relative_to(wf) for p in wf.rglob("*") if p.is_file()}
        assert all_files == {Path("WORKFLOW-GUIDE.md")}
        # 🔴 规则本体/tools/契约 MUST NOT 被铺进来 —— 它们走全局 canonical
        assert not (wf / "tools").exists()
        assert not (wf / "workflow.md").exists()
        assert not (wf / "lens-metric-contract.md").exists()
        assert not (wf / "spec-checklists").exists()
        assert not (wf / "code-checklists").exists()
        assert not (wf / "prompts").exists()

    def test_overwrite_guide_without_metadata_permission(self, tmp_path, monkeypatch):
        """回归锚（B38）：多用户共享目录下旧 GUIDE 属主是他人时，ACL 允许写内容，但
        utime / chmod 只有属主能做。覆盖 GUIDE MUST 只写内容、不复制元数据。"""
        wf = tmp_path / "openspec" / "workflow"
        wf.mkdir(parents=True)
        (wf / "WORKFLOW-GUIDE.md").write_text("stale", encoding="utf-8")

        def deny(*args, **kwargs):
            raise PermissionError(13, "Permission denied")
        monkeypatch.setattr(shutil, "copystat", deny)
        monkeypatch.setattr(os, "utime", deny)
        monkeypatch.setattr(os, "chmod", deny)

        copy_bundle(str(tmp_path), include_schema=False)
        src = Path(init_mod.BUNDLE_SRC) / "WORKFLOW-GUIDE.md"
        assert (wf / "WORKFLOW-GUIDE.md").read_bytes() == src.read_bytes()

    def test_fresh_init_does_not_raise(self, tmp_path):
        """回归锚（F15）：GUIDE 拷贝前若无 `os.makedirs(dst, exist_ok=True)`，fresh init
        （裸 tmp_path，无任何既有 openspec/workflow/ 目录——此前由 tools/ 的 copytree 隐式创建）
        会在此处抛 FileNotFoundError（ensure_dirs 的 CORE_DIRS 只有 changes/specs）。"""
        dst, n = copy_bundle(str(tmp_path), include_schema=False)   # 不应抛异常
        assert Path(dst).is_dir()
        assert (Path(dst) / "WORKFLOW-GUIDE.md").is_file()

    def test_include_schema_still_deploys_project_local_schema(self, tmp_path):
        dst, n = copy_bundle(str(tmp_path), include_schema=True)
        schema_dst = tmp_path / "openspec" / "schemas" / init_mod.PROJECT_SCHEMA / "schema.yaml"
        assert schema_dst.is_file()


class TestCopyBundleLeavesExistingWorkflowFilesAlone:
    """copy_bundle 不再部署规则/tools/ 子树 ⇒ 消费仓 openspec/workflow/ 下任何既有文件
    （历史遗留的规则副本、旧版 tools/ 等）字节不变——copy_bundle 只碰它自己铺的 GUIDE + schema。"""

    def test_update_preserves_preexisting_workflow_files(self, tmp_path):
        wf = tmp_path / "openspec" / "workflow"
        wf.mkdir(parents=True)
        # 模拟历史遗留：消费仓 openspec/workflow/ 已有旧版规则文件
        (wf / "workflow.md").write_text("# legacy rules v1\n", encoding="utf-8")
        (wf / "spec-checklists").mkdir()
        (wf / "spec-checklists" / "base.md").write_text("# base\n", encoding="utf-8")
        before = {
            "workflow.md": (wf / "workflow.md").read_bytes(),
            "spec-checklists/base.md": (wf / "spec-checklists" / "base.md").read_bytes(),
        }
        copy_bundle(str(tmp_path))
        # 既有文件字节不变
        assert (wf / "workflow.md").read_bytes() == before["workflow.md"]
        assert (wf / "spec-checklists" / "base.md").read_bytes() == before["spec-checklists/base.md"]
        # GUIDE 正常铺入
        assert (wf / "WORKFLOW-GUIDE.md").is_file()


class TestProjectLocalSchema:
    def _version(self, monkeypatch, value="1.7.0\n", returncode=0):
        """Fake only the `openspec --version` probe (`_openspec_cli_version`'s subprocess
        call) — MUST NOT blanket-replace `subprocess.run` for the whole module: `_yq()`
        (shared-yaml-subset-parser) also calls `subprocess.run` (yq's own `--version`
        identity check + the actual yq invocation), and a blanket stub would feed those
        calls the same fake "openspec version" stdout, corrupting yq's real output."""
        class Proc:
            stdout = value
            stderr = ""
            pass
        Proc.returncode = returncode
        real_run = init_mod.subprocess.run

        def fake_run(cmd, *a, **k):
            is_yq = isinstance(cmd, list) and cmd and "yq" in os.path.basename(cmd[0]).lower()
            if isinstance(cmd, list) and cmd and cmd[-1] == "--version" and not is_yq:
                return Proc()
            return real_run(cmd, *a, **k)

        monkeypatch.setattr(init_mod.subprocess, "run", fake_run)

    def _project(self, tmp_path):
        root = tmp_path / "project"
        (root / "openspec" / "changes" / "active").mkdir(parents=True)
        (root / "openspec" / "changes" / "active" / "proposal.md").write_text("# proposal\n", encoding="utf-8")
        (root / "openspec" / "config.yaml").write_text("schema: spec-driven\ncontext: keep\n", encoding="utf-8")
        return root

    def test_old_cli_does_not_deploy_schema_or_switch_config(self, tmp_path, monkeypatch, capsys):
        root = self._project(tmp_path)
        self._version(monkeypatch, "1.6.9\n")
        init_mod.run(str(root), "update")
        assert not (root / "openspec" / "schemas").exists()
        assert (root / "openspec" / "config.yaml").read_text(encoding="utf-8").startswith("schema: spec-driven")
        assert "版本门：不铺 project-local schema" in capsys.readouterr().out

    def test_semver_numeric_gate_accepts_1_10(self, tmp_path, monkeypatch):
        root = self._project(tmp_path)
        self._version(monkeypatch, "1.10.0\n")
        init_mod.run(str(root), "update")
        assert (root / "openspec" / "schemas" / "g-spec-driven" / "schema.yaml").is_file()
        assert (root / "openspec" / "config.yaml").read_text(encoding="utf-8").startswith("schema: g-spec-driven")

    def test_missing_or_non_numeric_cli_fails_closed(self, tmp_path, monkeypatch):
        root = self._project(tmp_path)
        self._version(monkeypatch, "openspec version unknown\n")
        init_mod.run(str(root), "update")
        assert not (root / "openspec" / "schemas").exists()
        assert "schema: spec-driven" in (root / "openspec" / "config.yaml").read_text(encoding="utf-8")

    def test_missing_cli_fails_closed(self, tmp_path, monkeypatch):
        root = self._project(tmp_path)

        def missing_cli(*args, **kwargs):
            raise OSError("openspec: command not found")

        monkeypatch.setattr(init_mod.subprocess, "run", missing_cli)
        init_mod.run(str(root), "update")

        assert not (root / "openspec" / "schemas").exists()
        assert (root / "openspec" / "config.yaml").read_text(encoding="utf-8").startswith(
            "schema: spec-driven"
        )

    def test_missing_cli_completes_but_warns_main_flow_unavailable(self, tmp_path, monkeypatch, capsys):
        """CLI 不可用时 init 仍按降级路径铺设，但 MUST 明说主流程暂不可用——不能只打 ✓ 完成（假绿）。"""
        root = tmp_path / "fresh"
        root.mkdir()
        monkeypatch.setattr(init_mod, "_openspec_cli_version", lambda: (None, "命令不可用"))
        monkeypatch.setattr(init_mod, "_check_yq", lambda: (True, None))
        monkeypatch.setattr(init_mod, "ensure_global_hooks", lambda: "stub")
        monkeypatch.setattr(init_mod, "retire_hooks", lambda: "stub")
        init_mod.run(str(root), "init")
        out = capsys.readouterr().out
        assert "依赖未齐" in out and "OpenSpec CLI" in out and "/g-spec" in out
        assert "yq" not in out.split("依赖未齐", 1)[1]

    def test_schema_gate_open_but_yq_missing_dies_before_touching_fs(self, tmp_path, monkeypatch, capsys):
        """版本门通过而 yq 不可用：MUST 在动文件系统前 fail-closed，并报 yq 这个真因
        （而非被 schema 校验折成「权威资产不可读取」），不留 openspec/ 半成品。"""
        root = tmp_path / "fresh"
        root.mkdir()
        monkeypatch.setattr(init_mod, "_openspec_cli_version", lambda: ((1, 16, 0), None))
        monkeypatch.setattr(init_mod.shutil, "which",
                            lambda name, *a, **k: None if name == "yq" else shutil.which(name, *a, **k))
        with pytest.raises(SystemExit) as exc:
            init_mod.run(str(root), "init")
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "yq 未安装" in err and "权威资产" not in err
        assert not (root / "openspec").exists()

    def test_update_with_yq_missing_leaves_project_untouched(self, tmp_path, monkeypatch):
        root = self._project(tmp_path)
        before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
        config = (root / "openspec" / "config.yaml").read_bytes()
        monkeypatch.setattr(init_mod, "_openspec_cli_version", lambda: ((1, 16, 0), None))
        monkeypatch.setattr(init_mod, "_check_yq", lambda: (False, "yq 未安装。"))
        with pytest.raises(SystemExit):
            init_mod.run(str(root), "update")
        assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == before
        assert (root / "openspec" / "config.yaml").read_bytes() == config

    def test_migration_failure_stops_before_schema_and_config_switch(self, tmp_path, monkeypatch):
        root = self._project(tmp_path)
        original_config = (root / "openspec" / "config.yaml").read_bytes()
        self._version(monkeypatch)

        real_replace = init_mod.os.replace

        def fail_marker_publish(src, dst):
            if str(dst).endswith(".openspec.yaml"):
                raise OSError("injected migration publish failure")
            return real_replace(src, dst)

        monkeypatch.setattr(init_mod.os, "replace", fail_marker_publish)
        with pytest.raises(SystemExit) as exc:
            init_mod.run(str(root), "update")

        assert exc.value.code == 1
        assert (root / "openspec" / "config.yaml").read_bytes() == original_config
        assert not (root / "openspec" / "schemas").exists()
        assert not (root / "openspec" / "changes" / "active" / ".openspec.yaml").exists()

    def test_stray_directory_without_proposal_is_ignored(self, tmp_path, monkeypatch):
        root = self._project(tmp_path)
        stray = root / "openspec" / "changes" / "stray"
        stray.mkdir()
        (stray / "notes.md").write_text("not a change\n", encoding="utf-8")
        self._version(monkeypatch)

        init_mod.run(str(root), "update")

        assert not (stray / ".openspec.yaml").exists()
        assert (root / "openspec" / "changes" / "active" / ".openspec.yaml").read_text(
            encoding="utf-8"
        ) == "schema: spec-driven\n"

    def test_migration_only_in_progress_and_idempotent(self, tmp_path, monkeypatch):
        root = self._project(tmp_path)
        (root / "openspec" / "changes" / "active" / ".openspec.yaml").unlink(missing_ok=True)
        archived = root / "openspec" / "changes" / "archive" / "20200101-old"
        archived.mkdir(parents=True)
        (archived / "proposal.md").write_text("# old\n", encoding="utf-8")
        self._version(monkeypatch)
        init_mod.run(str(root), "update")
        marker = root / "openspec" / "changes" / "active" / ".openspec.yaml"
        assert marker.read_text(encoding="utf-8") == "schema: spec-driven\n"
        assert not (archived / ".openspec.yaml").exists()
        init_mod.run(str(root), "update")
        assert marker.read_text(encoding="utf-8") == "schema: spec-driven\n"

    def test_update_accepts_existing_fork_bound_change(self, tmp_path, monkeypatch):
        root = self._project(tmp_path)
        self._version(monkeypatch)
        init_mod.run(str(root), "update")

        fork_bound = root / "openspec" / "changes" / "new-fork-bound"
        fork_bound.mkdir()
        (fork_bound / "proposal.md").write_text("# proposal\n", encoding="utf-8")
        marker = fork_bound / ".openspec.yaml"
        marker.write_text(f"schema: {init_mod.PROJECT_SCHEMA}\n", encoding="utf-8")

        init_mod.run(str(root), "update")

        assert marker.read_text(encoding="utf-8") == f"schema: {init_mod.PROJECT_SCHEMA}\n"
        assert (root / "openspec" / "config.yaml").read_text(encoding="utf-8").startswith(
            f"schema: {init_mod.PROJECT_SCHEMA}"
        )

    def test_migration_accepts_marker_with_extra_keys(self, tmp_path):
        """openspec CLI writes created/skip_specs etc alongside schema."""
        root = self._project(tmp_path)
        fork_bound = root / "openspec" / "changes" / "active"
        fork_bound.mkdir(parents=True, exist_ok=True)
        (fork_bound / "proposal.md").write_text("# proposal\n", encoding="utf-8")
        marker = fork_bound / ".openspec.yaml"
        marker.write_text(
            f"schema: {init_mod.PROJECT_SCHEMA}\ncreated: 2026-08-13\nskip_specs: true\n",
            encoding="utf-8",
        )
        count = init_mod.migrate_changes(str(root), init_mod.PROJECT_SCHEMA)
        assert count == 0
        assert marker.read_text(encoding="utf-8").startswith(f"schema: {init_mod.PROJECT_SCHEMA}")

    @pytest.mark.parametrize("content", ["schema: ", "not-schema: value\n"])
    def test_migration_rejects_unparseable_existing_marker(self, tmp_path, content):
        root = self._project(tmp_path)
        marker = root / "openspec" / "changes" / "active" / ".openspec.yaml"
        marker.write_text(content, encoding="utf-8")

        with pytest.raises(RuntimeError, match="marker"):
            init_mod.migrate_changes(str(root), "spec-driven")

    def test_migration_leaves_change_on_consumer_owned_schema_alone(self, tmp_path):
        """消费仓可在 openspec/schemas/ 下维护自己的 project-local schema；钉在它上面的在途 change
        不是坏 marker——update 不得因此整体失败，也不得改写它。"""
        root = self._project(tmp_path)
        marker = root / "openspec" / "changes" / "active" / ".openspec.yaml"
        marker.write_text("schema: my-schema\n", encoding="utf-8")

        assert init_mod.migrate_changes(str(root), "spec-driven") == 0
        assert marker.read_text(encoding="utf-8") == "schema: my-schema\n"

    def test_update_with_custom_schema_change_completes(self, tmp_path, monkeypatch):
        root = self._project(tmp_path)
        marker = root / "openspec" / "changes" / "active" / ".openspec.yaml"
        marker.write_text("schema: my-schema\n", encoding="utf-8")
        self._version(monkeypatch)
        init_mod.run(str(root), "update")
        assert marker.read_text(encoding="utf-8") == "schema: my-schema\n"
        assert (root / "openspec" / "schemas" / "g-spec-driven" / "schema.yaml").is_file()

    def test_non_filesystem_error_is_not_labelled_as_filesystem_failure(self, tmp_path, monkeypatch, capsys):
        root = self._project(tmp_path)
        marker = root / "openspec" / "changes" / "active" / ".openspec.yaml"
        marker.write_text("not-schema: value\n", encoding="utf-8")
        self._version(monkeypatch)
        with pytest.raises(SystemExit):
            init_mod.run(str(root), "update")
        err = capsys.readouterr().err
        assert "g-init update 中止" in err and "marker" in err
        assert "文件系统操作失败" not in err

    def test_update_without_cli_keeps_project_schema_key(self, tmp_path, monkeypatch, capsys):
        """B7：CLI 不可用（版本未知）≠ CLI 过旧。前者 MUST NOT 把 config 从 g-spec-driven 降回内置。"""
        root = self._project(tmp_path)
        config = root / "openspec" / "config.yaml"
        config.write_text("schema: g-spec-driven\ncontext: keep\n", encoding="utf-8")

        def missing_cli(*args, **kwargs):
            raise OSError("openspec: command not found")

        monkeypatch.setattr(init_mod, "_check_yq", lambda: (True, None))
        monkeypatch.setattr(init_mod.subprocess, "run", missing_cli)
        init_mod.run(str(root), "update")
        assert config.read_text(encoding="utf-8") == "schema: g-spec-driven\ncontext: keep\n"
        out = capsys.readouterr().out
        assert "未改 schema 键" in out and "g-spec-driven" in out

    def test_update_with_old_cli_still_downgrades_project_schema_key(self, tmp_path, monkeypatch):
        """版本可解析且 < 1.7.0：旧 CLI 读不了 fork，降到内置 schema 仍是正确行为。"""
        root = self._project(tmp_path)
        config = root / "openspec" / "config.yaml"
        config.write_text("schema: g-spec-driven\ncontext: keep\n", encoding="utf-8")
        self._version(monkeypatch, "1.6.9\n")
        init_mod.run(str(root), "update")
        assert config.read_text(encoding="utf-8") == "schema: spec-driven\ncontext: keep\n"

    def test_update_changes_only_schema_line(self, tmp_path, monkeypatch):
        root = self._project(tmp_path)
        original = "schema: spec-driven\ncontext: keep\n# schema: elsewhere\n"
        (root / "openspec" / "config.yaml").write_text(original, encoding="utf-8")
        self._version(monkeypatch)
        init_mod.run(str(root), "update")
        assert (root / "openspec" / "config.yaml").read_text(encoding="utf-8") == original.replace(
            "schema: spec-driven", "schema: g-spec-driven", 1
        )

    def test_update_inserts_missing_schema_key_without_losing_config_bytes(self, tmp_path):
        root = self._project(tmp_path)
        original = b"context: keep\r\nmetrics:\r\n  enabled: true\r\n"
        config = root / "openspec" / "config.yaml"
        config.write_bytes(original)

        status, _ = init_mod.handle_config(str(root), "update", schema=init_mod.PROJECT_SCHEMA)

        assert status == "updated"
        assert config.read_bytes() == b"schema: g-spec-driven\r\n" + original

    def test_update_preserves_schema_inline_comment_and_suffix_bytes(self, tmp_path):
        root = self._project(tmp_path)
        original = b"schema: spec-driven  # legacy choice\r\ncontext: keep\r\n"
        config = root / "openspec" / "config.yaml"
        config.write_bytes(original)

        status, _ = init_mod.handle_config(str(root), "update", schema=init_mod.PROJECT_SCHEMA)

        assert status == "updated"
        assert config.read_bytes() == original.replace(
            b"spec-driven", b"g-spec-driven", 1
        )

    @pytest.mark.parametrize("prefix", [b"", b"\xef\xbb\xbf"])
    def test_update_writes_comment_only_schema_with_yaml_comment_separator(self, tmp_path, prefix):
        root = self._project(tmp_path)
        original = prefix + b"schema:    # local choice\r\ncontext: keep\r\n"
        config = root / "openspec" / "config.yaml"
        config.write_bytes(original)

        status, _ = init_mod.handle_config(str(root), "update", schema=init_mod.PROJECT_SCHEMA)

        assert status == "updated"
        assert config.read_bytes() == prefix + (
            b"schema:    g-spec-driven # local choice\r\ncontext: keep\r\n"
        )
        assert init_mod._schema_from_config(str(root)) == init_mod.PROJECT_SCHEMA

    def test_update_inserts_schema_after_commented_document_start(self, tmp_path):
        root = self._project(tmp_path)
        original = b"--- # local config\r\ncontext: keep\r\n"
        config = root / "openspec" / "config.yaml"
        config.write_bytes(original)

        status, _ = init_mod.handle_config(str(root), "update", schema=init_mod.PROJECT_SCHEMA)

        assert status == "updated"
        assert config.read_bytes() == (
            b"--- # local config\r\nschema: g-spec-driven\r\ncontext: keep\r\n"
        )
        assert init_mod._schema_from_config(str(root)) == init_mod.PROJECT_SCHEMA

    def test_update_inserts_schema_after_prefixed_comments_and_blank_lines(self, tmp_path):
        root = self._project(tmp_path)
        original = b"# local note\r\n\r\n--- # local config\r\ncontext: keep\r\n"
        config = root / "openspec" / "config.yaml"
        config.write_bytes(original)

        status, _ = init_mod.handle_config(str(root), "update", schema=init_mod.PROJECT_SCHEMA)

        assert status == "updated"
        assert config.read_bytes() == (
            b"# local note\r\n\r\n--- # local config\r\nschema: g-spec-driven\r\ncontext: keep\r\n"
        )

    def test_update_inserts_schema_after_yaml_directives_and_document_start(self, tmp_path):
        root = self._project(tmp_path)
        original = b"%YAML 1.2\r\n%TAG !e! tag:example.com,2020:\r\n--- # local config\r\ncontext: keep\r\n"
        config = root / "openspec" / "config.yaml"
        config.write_bytes(original)

        status, _ = init_mod.handle_config(str(root), "update", schema=init_mod.PROJECT_SCHEMA)

        assert status == "updated"
        assert config.read_bytes() == (
            b"%YAML 1.2\r\n%TAG !e! tag:example.com,2020:\r\n--- # local config\r\n"
            b"schema: g-spec-driven\r\ncontext: keep\r\n"
        )

    def test_update_rewrites_bom_crlf_schema_once_and_preserves_other_bytes(self, tmp_path):
        root = self._project(tmp_path)
        original = b"\xef\xbb\xbfschema: spec-driven  # legacy choice\r\ncontext: keep\r\n"
        config = root / "openspec" / "config.yaml"
        config.write_bytes(original)

        assert init_mod._schema_from_config(str(root)) == "spec-driven"
        status, _ = init_mod.handle_config(str(root), "update", schema=init_mod.PROJECT_SCHEMA)
        actual = config.read_bytes()

        assert status == "updated"
        assert actual == original.replace(b"spec-driven", b"g-spec-driven", 1)
        assert actual.startswith(b"\xef\xbb\xbf")
        assert actual.count(b"schema:") == 1

    def test_update_preserves_schema_key_spacing_before_colon(self, tmp_path):
        root = self._project(tmp_path)
        config = root / "openspec" / "config.yaml"
        config.write_bytes(b"schema : spec-driven  # legacy\r\ncontext: keep\r\n")

        status, _ = init_mod.handle_config(str(root), "update", schema=init_mod.PROJECT_SCHEMA)

        assert status == "updated"
        assert config.read_bytes() == b"schema : g-spec-driven  # legacy\r\ncontext: keep\r\n"
        assert config.read_bytes().count(b"schema") == 1

    def test_schema_bundle_prunes_orphans(self, tmp_path):
        root = tmp_path / "project"
        dst = root / "openspec" / "schemas" / "g-spec-driven"
        dst.mkdir(parents=True)
        (dst / "orphan.txt").write_text("stale\n", encoding="utf-8")
        copy_bundle(str(root))
        assert not (dst / "orphan.txt").exists()
        assert (dst / "schema.yaml").is_file()

    def test_schema_bundle_preserves_sibling_schemas(self, tmp_path):
        root = tmp_path / "project"
        sibling = root / "openspec" / "schemas" / "consumer-owned"
        sibling.mkdir(parents=True)
        (sibling / "schema.yaml").write_text("custom: true\n", encoding="utf-8")

        copy_bundle(str(root))

        assert (sibling / "schema.yaml").read_text(encoding="utf-8") == "custom: true\n"

    def test_schema_bundle_missing_authority_fails_loudly(self, tmp_path, monkeypatch):
        root = tmp_path / "project"
        missing = tmp_path / "missing-schema-assets"
        monkeypatch.setattr(init_mod, "SCHEMAS_SRC", str(missing))

        with pytest.raises(RuntimeError, match="权威资产缺失"):
            copy_bundle(str(root), include_schema=True)

    def test_update_missing_schema_authority_does_not_switch_config(self, tmp_path, monkeypatch):
        root = self._project(tmp_path)
        config = root / "openspec" / "config.yaml"
        original = config.read_bytes()
        self._version(monkeypatch)
        monkeypatch.setattr(init_mod, "SCHEMAS_SRC", str(tmp_path / "missing-schema-assets"))

        with pytest.raises(SystemExit) as exc:
            init_mod.run(str(root), "update")

        assert exc.value.code == 1
        assert config.read_bytes() == original

    def test_update_missing_referenced_template_does_not_prune_or_switch_config(self, tmp_path, monkeypatch):
        root = self._project(tmp_path)
        config = root / "openspec" / "config.yaml"
        original_config = config.read_bytes()
        authority = tmp_path / "schema-authority"
        source_schema = Path(init_mod.SCHEMAS_SRC) / init_mod.PROJECT_SCHEMA
        shutil.copytree(source_schema, authority / init_mod.PROJECT_SCHEMA)
        (authority / init_mod.PROJECT_SCHEMA / "templates" / "spec.md").unlink()
        monkeypatch.setattr(init_mod, "SCHEMAS_SRC", str(authority))
        self._version(monkeypatch)

        managed = root / "openspec" / "schemas" / init_mod.PROJECT_SCHEMA
        managed.mkdir(parents=True)
        managed_schema = managed / "schema.yaml"
        managed_schema.write_text("name: old-managed-fork\n", encoding="utf-8")

        with pytest.raises(SystemExit) as exc:
            init_mod.run(str(root), "update")

        assert exc.value.code == 1
        assert config.read_bytes() == original_config
        assert managed_schema.read_text(encoding="utf-8") == "name: old-managed-fork\n"


class TestUpdateDoesNotDeployRules:
    """fix-probe-scan-precision：--dev/full 整 bundle 刷新已退役——普通 update 从不铺规则本体，
    无论 init 还是 update 都只铺 GUIDE + schema。"""

    def _seeded(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fake-claude"))
        root = tmp_path / "proj"
        init_mod.run(str(root), "init")
        return root

    def test_plain_update_does_not_deploy_rules(self, tmp_path, monkeypatch):
        root = self._seeded(tmp_path, monkeypatch)
        init_mod.run(str(root), "update")
        assert not (root / "openspec" / "workflow" / "workflow.md").exists()


class TestHandleConfigFromBundleSrc:
    """2.5：config 模版改读 BUNDLE_SRC——消费仓无规则副本时 init 不得 FileNotFoundError。"""

    def test_init_creates_config_without_consumer_template(self, tmp_path):
        root = tmp_path / "proj"
        (root / "openspec").mkdir(parents=True)    # 无 workflow/config.template.yaml
        status, _ = init_mod.handle_config(str(root), "init")
        assert status == "created"
        assert (root / "openspec" / "config.yaml").is_file()


class TestStaleShadowWarnings:
    """R-MRF-3：残留死件（规则副本 / tools/ / lens-metric-contract.md / 孤儿 checkpoint）
    只告警绝不删（反静默守卫·陈旧遮蔽死件变体，fix-probe-scan-precision task 4）。"""

    def _legacy_consumer(self, tmp_path):
        root = tmp_path / "old"
        wf = root / "openspec" / "workflow"
        wf.mkdir(parents=True)
        (wf / "workflow.md").write_text("# old rules\n", encoding="utf-8")
        (root / "hack").mkdir()
        (root / "hack" / "checkpoint-commit.sh").write_text("#!/bin/bash\n", encoding="utf-8")
        return root

    def test_warns_on_residual_rules_and_orphan_hack_without_deleting(self, tmp_path):
        root = self._legacy_consumer(tmp_path)
        warns = init_mod.stale_shadow_warnings(str(root))
        assert any("死件" in w for w in warns)
        assert any("checkpoint-commit.sh" in w for w in warns)
        assert (root / "openspec" / "workflow" / "workflow.md").exists()   # 绝不删
        assert (root / "hack" / "checkpoint-commit.sh").exists()

    def test_truly_clean_consumer_no_warnings(self, tmp_path):
        # 真正干净：openspec/workflow/ 下无任何 RULE_MARKERS、无 tools/、无 contract、无孤儿 hack。
        root = tmp_path / "clean"
        (root / "openspec" / "workflow").mkdir(parents=True)
        assert init_mod.stale_shadow_warnings(str(root)) == []

    def test_tools_only_residual_now_warns(self, tmp_path):
        # 判据扩员（task 4.1）：tools/ 目录残留（即便无 RULE_MARKERS 规则本体）本身即死件，
        # MUST 报警——旧实现只查 RULE_MARKERS 三项、会漏掉这块最大的残留（此用例在旧实现上必绿，
        # 是本次判据扩员的反向锚：改回旧 RULE_MARKERS 判据会让本用例红）。
        root = tmp_path / "tools-only"
        wf = root / "openspec" / "workflow" / "tools"
        wf.mkdir(parents=True)
        (wf / "anchor_lint.py").write_text("x", encoding="utf-8")
        warns = init_mod.stale_shadow_warnings(str(root))
        assert any("死件" in w and "tools" in w for w in warns)

    def test_lens_metric_contract_residual_now_warns(self, tmp_path):
        # 判据扩员（task 4.1）：lens-metric-contract.md 残留同为死件。
        root = tmp_path / "contract-only"
        wf = root / "openspec" / "workflow"
        wf.mkdir(parents=True)
        (wf / "lens-metric-contract.md").write_text("# contract\n", encoding="utf-8")
        warns = init_mod.stale_shadow_warnings(str(root))
        assert any("死件" in w and "lens-metric-contract.md" in w for w in warns)

    def test_message_wording_positive_and_negative(self, tmp_path):
        """task 4.4：文案双断言——不含旧「显式 pin」/「遮蔽全局」措辞，含新死件关键词 + 前置条件 +
        可复制删除命令；只断言"含新词"会让旧文案叠加新词也通过，故须双断言。"""
        root = self._legacy_consumer(tmp_path)
        warns = init_mod.stale_shadow_warnings(str(root))
        joined = "\n".join(warns)
        # 负断言：旧的「留=pin/遮蔽全局」措辞必须被清除
        assert "显式 pin" not in joined
        assert "遮蔽全局" not in joined
        # 正断言：新死件文案关键词 + 前置条件提示 + 可复制删除命令
        assert "死件" in joined
        assert "bash setup.sh" in joined   # 前置条件：先跑 setup 再判断
        assert "rm -rf" in joined and "rm -f" in joined   # 可复制删除命令（workflow 残留 + hack 孤儿）

    def test_clean_consumer_no_warnings(self, tmp_path):
        root = tmp_path / "clean"
        os.makedirs(str(root / "openspec"))
        assert init_mod.stale_shadow_warnings(str(root)) == []

    def test_update_prints_warnings(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fake-claude"))
        root = self._legacy_consumer(tmp_path)
        init_mod.run(str(root), "update")
        out = capsys.readouterr().out
        assert "死件" in out
        assert (root / "openspec" / "workflow" / "workflow.md").exists()


class TestEnsureGlobalHooks:
    def _settings_path(self, home):
        return home / "settings.json"

    def test_installs_and_registers_a_new_hook_spec(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
        src = tmp_path / "myhook.py"
        src.write_text("print('hi')\n", encoding="utf-8")
        spec = {
            "name": "myhook.py",
            "src": str(src),
            "event": "PostToolUse",
            "matcher": "Bash",
            "cmd": 'python3 "$HOME/.claude/hooks/myhook.py"',
        }
        msg = init_mod.ensure_global_hook(spec)
        assert "安装" in msg
        assert (home / "hooks" / "myhook.py").is_file()
        data = json.loads(self._settings_path(home).read_text(encoding="utf-8"))
        assert data["hooks"]["PostToolUse"][0]["matcher"] == "Bash"
        assert "myhook.py" in data["hooks"]["PostToolUse"][0]["hooks"][0]["command"]

    def test_rerun_is_idempotent_no_duplicate_registration(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
        src = tmp_path / "myhook.py"
        src.write_text("print('hi')\n", encoding="utf-8")
        spec = {
            "name": "myhook.py",
            "src": str(src),
            "event": "PostToolUse",
            "matcher": "Bash",
            "cmd": 'python3 "$HOME/.claude/hooks/myhook.py"',
        }
        init_mod.ensure_global_hook(spec)
        init_mod.ensure_global_hook(spec)
        data = json.loads(self._settings_path(home).read_text(encoding="utf-8"))
        assert len(data["hooks"]["PostToolUse"]) == 1

    def test_two_different_hooks_land_in_their_own_event_lists(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
        pre_src = tmp_path / "pre.py"
        pre_src.write_text("print('pre')\n", encoding="utf-8")
        post_src = tmp_path / "post.py"
        post_src.write_text("print('post')\n", encoding="utf-8")
        init_mod.ensure_global_hook({
            "name": "pre.py", "src": str(pre_src), "event": "PreToolUse",
            "matcher": "Bash", "cmd": 'python3 "$HOME/.claude/hooks/pre.py"',
        })
        init_mod.ensure_global_hook({
            "name": "post.py", "src": str(post_src), "event": "PostToolUse",
            "matcher": "Bash", "cmd": 'python3 "$HOME/.claude/hooks/post.py"',
        })
        data = json.loads(self._settings_path(home).read_text(encoding="utf-8"))
        assert len(data["hooks"]["PreToolUse"]) == 1
        assert len(data["hooks"]["PostToolUse"]) == 1

    def test_preexisting_single_hook_registration_still_recognized(self, tmp_path, monkeypatch):
        """Backward compat: a settings.json written by the OLD single-hook ensure_global_hook()
        must still be recognized as 'already registered' by the new generalized version."""
        home = tmp_path / "home"
        home.mkdir()
        (home / "hooks").mkdir()
        src = tmp_path / "ff0.py"
        src.write_text("print('ff0')\n", encoding="utf-8")
        (home / "hooks" / "ff0.py").write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
        (self._settings_path(home)).write_text(json.dumps({
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": 'python3 "$HOME/.claude/hooks/ff0.py"'}
            ]}]}
        }), encoding="utf-8")
        spec = {
            "name": "ff0.py", "src": str(src), "event": "PreToolUse",
            "matcher": "Bash", "cmd": 'python3 "$HOME/.claude/hooks/ff0.py"',
        }
        msg = init_mod.ensure_global_hook(spec)
        assert "已注册" in msg
        data = json.loads(self._settings_path(home).read_text(encoding="utf-8"))
        assert len(data["hooks"]["PreToolUse"]) == 1  # not duplicated


class TestGlobalHookInstall:
    """全局 hook 经 `init` 入口装进 CLAUDE_CONFIG_DIR/hooks 并注册：注册命令的解释器在注册时
    探测（真能跑才用），脚本路径展开到实际落盘位置；子代理权限守卫已退役，存量安装被摘除。
    期望值取自字面（hook 名、事件、matcher），不从 HOOKS 推导。"""

    GUARD = "subagent-permission-guard.py"
    FF0 = "ff0-branch-guard.py"
    SCRIPT = '"${CLAUDE_CONFIG_DIR:-$HOME/.claude}/hooks/ff0-branch-guard.py"'

    @pytest.fixture(autouse=True)
    def _real_claude_untouched(self):
        """真实 ~/.claude 的 settings.json 字节与 hooks/ 清单在用例前后不变。"""
        real = Path(os.path.expanduser("~")) / ".claude"

        def snap():
            settings = real / "settings.json"
            hooks = real / "hooks"
            return (
                settings.read_bytes() if settings.is_file() else None,
                sorted(p.name for p in hooks.iterdir()) if hooks.is_dir() else None,
            )

        before = snap()
        yield
        assert snap() == before, "真实 ~/.claude 被测试改动了"

    def _init_twice(self, tmp_path, monkeypatch, seed_settings=None, second_mode="init", seed_scripts=()):
        """seed_settings：init 前写入 settings.json 的内容（dict），None 则不写。"""
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
        if seed_settings is not None:
            (home / "settings.json").write_text(json.dumps(seed_settings), encoding="utf-8")
        if seed_scripts:
            (home / "hooks").mkdir()
            for name in seed_scripts:
                (home / "hooks" / name).write_text("# old install\n", encoding="utf-8")
        root = tmp_path / "proj"
        root.mkdir()
        init_mod.run(str(root), "init")
        init_mod.run(str(root), second_mode)
        return home, root

    def _settings(self, home):
        return json.loads((home / "settings.json").read_text(encoding="utf-8"))

    def _expected_cmd(self):
        return f"{init_mod._hook_interpreter()} {self.SCRIPT}"

    def test_hook_set_is_exactly_the_branch_guard(self):
        assert {h["name"] for h in init_mod.HOOKS} == {self.FF0}
        ff0 = init_mod.HOOKS[0]
        assert ff0["event"] == "PreToolUse"
        assert ff0["matcher"] == "Bash"
        assert ff0["script"] == self.SCRIPT
        assert os.path.isfile(ff0["src"])

    def test_subagent_guard_is_retired_and_no_longer_shipped(self):
        assert self.GUARD in init_mod.RETIRED_HOOKS
        assert not os.path.exists(os.path.join(init_mod.ASSETS, "hooks", self.GUARD))

    def test_init_twice_installs_script_and_one_registration(self, tmp_path, monkeypatch, capsys):
        home, _ = self._init_twice(tmp_path, monkeypatch)
        capsys.readouterr()
        assert (home / "hooks" / self.FF0).is_file()
        assert not (home / "hooks" / self.GUARD).exists()
        data = self._settings(home)
        assert len(data["hooks"]["PreToolUse"]) == 1
        assert data["hooks"]["PreToolUse"][0]["hooks"][0]["command"] == self._expected_cmd()
        assert not data["hooks"].get("PermissionRequest")

    def test_registered_command_runs_the_installed_guard(self, tmp_path, monkeypatch, capsys):
        """真执行注册命令（解释器 + 落盘脚本），不拿 printf 替身：受保护分支上建 change 必须被拒。
        商店占位 python3 之类「存在但跑不起来」的解释器在这里会直接红。"""
        from test_support.windows import bash_executable
        home, _ = self._init_twice(tmp_path, monkeypatch)
        capsys.readouterr()
        cmd = self._settings(home)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init", "-q", "-b", "main", str(repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@e.invalid",
                        "commit", "-q", "--allow-empty", "-m", "init"], check=True, capture_output=True)
        payload = json.dumps({"tool_name": "Bash", "cwd": str(repo),
                              "tool_input": {"command": "openspec new change demo"}})
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(home), HOME=str(tmp_path / "some-other-home"))
        r = subprocess.run([bash_executable(), "-c", cmd], input=payload, env=env, cwd=str(repo),
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        assert r.returncode == 0, r.stderr
        assert '"permissionDecision": "deny"' in r.stdout, r.stdout + r.stderr

    def test_registered_script_path_expands_to_the_landing_path(self, tmp_path, monkeypatch, capsys):
        from test_support.windows import bash_executable
        home, _ = self._init_twice(tmp_path, monkeypatch)
        capsys.readouterr()
        cmd = self._settings(home)["hooks"]["PreToolUse"][0]["hooks"][0]["command"]
        assert cmd.endswith(" " + self.SCRIPT)
        env = dict(os.environ, CLAUDE_CONFIG_DIR=str(home), HOME=str(tmp_path / "some-other-home"))
        out = subprocess.run([bash_executable(), "-c", "printf %s " + self.SCRIPT], env=env,
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             check=True).stdout
        # Windows 上 CLAUDE_CONFIG_DIR 是反斜杠路径、拼接段是正斜杠：按规范化路径比较。
        assert os.path.normcase(os.path.normpath(out)) == os.path.normcase(str(home / "hooks" / self.FF0))
        assert os.path.isfile(out)

    def test_stale_own_registration_is_rewritten_once(self, tmp_path, monkeypatch, capsys):
        """存量注册写死 python3 + $HOME/.claude：命令改写为当前探测结果，不新增第二条。"""
        legacy_cmd = 'python3 "$HOME/.claude/hooks/ff0-branch-guard.py"'
        legacy_entry = {"matcher": "Bash", "hooks": [{"type": "command", "command": legacy_cmd}]}
        home, _ = self._init_twice(
            tmp_path, monkeypatch,
            seed_settings={"hooks": {"PreToolUse": [legacy_entry]}}, second_mode="update")
        capsys.readouterr()
        pre = self._settings(home)["hooks"]["PreToolUse"]
        assert len(pre) == 1
        assert pre[0]["matcher"] == "Bash"
        assert pre[0]["hooks"] == [{"type": "command", "command": self._expected_cmd()}]

    def test_foreign_command_mentioning_the_name_is_left_alone(self, tmp_path, monkeypatch, capsys):
        foreign = {"matcher": "Bash", "hooks": [
            {"type": "command", "command": "/opt/wrap.sh --audit ff0-branch-guard.py"}]}
        home, _ = self._init_twice(
            tmp_path, monkeypatch, seed_settings={"hooks": {"PreToolUse": [foreign]}})
        capsys.readouterr()
        assert foreign in self._settings(home)["hooks"]["PreToolUse"]

    def test_legacy_guard_install_is_retired_keeping_user_entries(self, tmp_path, monkeypatch, capsys):
        user_entry = {"matcher": "Bash", "hooks": [{"type": "command", "command": "/opt/my-perm-hook.sh"}]}
        guard_entry = {"matcher": "*", "hooks": [{"type": "command",
                       "command": f'python3 "${{CLAUDE_CONFIG_DIR:-$HOME/.claude}}/hooks/{self.GUARD}"'}]}
        home, _ = self._init_twice(
            tmp_path, monkeypatch,
            seed_settings={"hooks": {"PermissionRequest": [user_entry, guard_entry]}},
            seed_scripts=(self.GUARD,))
        capsys.readouterr()
        assert self._settings(home)["hooks"]["PermissionRequest"] == [user_entry]
        assert not (home / "hooks" / self.GUARD).exists()
        assert (home / "hooks" / self.FF0).is_file()


class TestHookInterpreterProbe:
    """`_hook_interpreter()`：按「真能跑」挑解释器，不按 PATH 上存在与否。"""

    def _fake(self, monkeypatch, which, rc):
        monkeypatch.setattr(init_mod.shutil, "which", lambda name, *a, **k: which.get(name))

        class Proc:
            def __init__(self, code):
                self.returncode = code

        def fake_run(cmd, *a, **k):
            return Proc(rc[cmd[0]])

        monkeypatch.setattr(init_mod.subprocess, "run", fake_run)

    def test_working_python3_is_preferred(self, monkeypatch):
        self._fake(monkeypatch, {"python3": "/bin/python3", "python": "/bin/python"},
                   {"/bin/python3": 0, "/bin/python": 0})
        assert init_mod._hook_interpreter() == "python3"

    def test_store_stub_python3_falls_back_to_python(self, monkeypatch):
        self._fake(monkeypatch, {"python3": "C:/WindowsApps/python3.exe", "python": "C:/Py/python.exe"},
                   {"C:/WindowsApps/python3.exe": 9009, "C:/Py/python.exe": 0})
        assert init_mod._hook_interpreter() == "python"

    def test_nothing_runnable_falls_back_to_current_interpreter(self, monkeypatch):
        self._fake(monkeypatch, {"python3": "C:/WindowsApps/python3.exe"},
                   {"C:/WindowsApps/python3.exe": 49})
        got = init_mod._hook_interpreter()
        assert got == '"' + sys.executable.replace("\\", "/") + '"'
        assert "\\" not in got


class TestDevTombstone:
    """fix-probe-scan-precision：`--dev` 退役，toolkit-仓根守卫随之删除；`run()` 不再接受
    `dev` 关键字参数（TypeError 是生产契约，非测试疏漏）。CLI 层保留一版 tombstone——
    识别到 `--dev` 参数 → fail-loud 提示，而非 argparse 的 generic「unrecognized arguments」。"""

    def test_run_no_longer_accepts_dev_kwarg(self, tmp_path):
        with pytest.raises(TypeError):
            init_mod.run(str(tmp_path), "update", dev=True)

    def test_cli_dev_flag_fails_loud_with_retirement_message(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fake-claude"))
        monkeypatch.setattr(sys, "argv", ["init.py", "update", "--dev", "--root", str(tmp_path)])
        with pytest.raises(SystemExit) as exc:
            init_mod.main()
        assert exc.value.code == 1
        err = capsys.readouterr().err
        assert "--dev 已退役" in err

    def test_cli_dev_flag_does_not_touch_filesystem(self, tmp_path, monkeypatch):
        """tombstone 须在任何文件系统操作之前拦下——不得半跑一截才报错。"""
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fake-claude"))
        monkeypatch.setattr(sys, "argv", ["init.py", "update", "--dev", "--root", str(tmp_path)])
        with pytest.raises(SystemExit):
            init_mod.main()
        assert not (tmp_path / "openspec").exists()


class TestInitAlsoWarnsShadow:
    """B2-F3：陈旧遮蔽告警按磁盘状态触发——init 也要跑，不再只挂 update。"""

    def test_init_on_legacy_repo_warns_shadow(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fake-claude"))
        root = tmp_path / "old"
        wf = root / "openspec" / "workflow"
        wf.mkdir(parents=True)
        (wf / "workflow.md").write_text("# old rules\n", encoding="utf-8")
        init_mod.run(str(root), "init")
        out = capsys.readouterr().out
        assert "死件" in out


class TestRunFsErrorGuard:
    """B1-F2：run() 主体 FS 操作异常须走 _die 惯例，不裸抛 traceback。"""

    def test_readonly_root_dies_with_fs_error(self, tmp_path, monkeypatch, capsys):
        if os.name == "nt":
            pytest.skip("Windows chmod does not enforce POSIX directory write permissions")
        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("running as root — permission bits don't block writes")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fake-claude"))
        root = tmp_path / "proj"
        root.mkdir()
        root.chmod(0o500)
        try:
            with pytest.raises(SystemExit):
                init_mod.run(str(root), "init")
            err = capsys.readouterr().err
            assert "文件系统操作失败" in err
        finally:
            root.chmod(0o700)


class TestInjectPreservesLineEndings:
    """C7：托管区块外的用户行逐字节不变；区块按文件既有换行风格写入（Windows 文本模式曾把
    整份 LF 文件改写成 CRLF，git diff 成整文件改动）。"""

    def _seed(self, tmp_path, eol, with_block=True):
        p = tmp_path / "CLAUDE.md"
        head = f"# Mine{eol}{eol}keep this line{eol}{eol}"
        block = (f"{init_mod.MARK_DOC[0]}{eol}old content{eol}{init_mod.MARK_DOC[1]}{eol}"
                 if with_block else "")
        tail = f"tail line{eol}" if with_block else ""
        p.write_bytes((head + block + tail).encode("utf-8"))
        return p, head, tail

    @pytest.mark.parametrize("eol", ["\n", "\r\n"])
    def test_replace_keeps_user_bytes_and_line_ending_style(self, tmp_path, eol):
        p, head, tail = self._seed(tmp_path, eol)
        init_mod.inject(str(p), *init_mod.MARK_DOC, "new line 1\nnew line 2\n")
        data = p.read_bytes().decode("utf-8")
        assert data.startswith(head)
        assert data.endswith(tail)
        assert f"new line 1{eol}new line 2{eol}" in data
        if eol == "\n":
            assert "\r" not in data
        else:
            assert data.count("\n") == data.count("\r\n")

    @pytest.mark.parametrize("eol", ["\n", "\r\n"])
    def test_append_keeps_user_bytes_and_line_ending_style(self, tmp_path, eol):
        p, head, _ = self._seed(tmp_path, eol, with_block=False)
        init_mod.inject(str(p), *init_mod.MARK_DOC, "body\n")
        data = p.read_bytes().decode("utf-8")
        assert data.startswith(head.rstrip("\r\n"))
        assert f"{init_mod.MARK_DOC[1]}{eol}" in data
        if eol == "\n":
            assert "\r" not in data
        else:
            assert data.count("\n") == data.count("\r\n")

    def test_new_file_is_written_with_lf(self, tmp_path):
        p = tmp_path / "AGENTS.md"
        init_mod.inject(str(p), *init_mod.MARK_DOC, "body\n", header="# AGENTS")
        assert b"\r" not in p.read_bytes()


class TestInjectMarkerMigration:
    """0.2：inject() 改 token 基定位——旧 marker 文案（opsx-project-init）区块被替换而非追加重复。"""

    OLD_BLOCK = ("<!-- opsx-init:start —— 由 opsx-project-init 维护，勿手改本区块 -->\n"
                 "旧内容\n<!-- opsx-init:end -->\n")

    def test_old_marker_block_replaced_not_duplicated(self, tmp_path):
        f = tmp_path / "CLAUDE.md"
        f.write_text("# 头\n\n" + self.OLD_BLOCK + "\n尾部用户内容\n", encoding="utf-8")
        init_mod.inject(str(f), *init_mod.MARK_DOC, "新内容")
        text = f.read_text(encoding="utf-8")
        assert text.count("opsx-init:start") == 1        # 只有一个区块（替换，非追加）
        assert "新内容" in text and "旧内容" not in text
        assert "g-init 维护" in text                 # marker 文案已随替换更新
        assert "尾部用户内容" in text                     # 区块外内容无损

    def test_fresh_file_gets_new_marker(self, tmp_path):
        f = tmp_path / "CLAUDE.md"
        init_mod.inject(str(f), *init_mod.MARK_DOC, "内容", header="# H")
        assert "g-init 维护" in f.read_text(encoding="utf-8")

    def test_nested_managed_content_keeps_separator_after_outer_marker(self, tmp_path):
        """--dev update 不得破坏 sync_principles 的 canonical 空行布局。"""
        f = tmp_path / "CLAUDE.md"
        nested = "<!-- g:principles:start -->\n通则\n<!-- g:principles:end -->"
        init_mod.inject(str(f), *init_mod.MARK_DOC, nested)
        assert f"{init_mod.MARK_DOC[0]}\n\n{nested}" in f.read_text(encoding="utf-8")

    def test_ordinary_index_content_has_no_nested_separator(self, tmp_path):
        """普通 MARK_IDX 内容不能因 nested 专用格式化而多出空行。"""
        f = tmp_path / "INDEX.md"
        init_mod.inject(str(f), *init_mod.MARK_IDX, "## 索引\n")
        assert f.read_text(encoding="utf-8") == (
            f"{init_mod.MARK_IDX[0]}\n## 索引\n{init_mod.MARK_IDX[1]}\n"
        )

    OLD_IDX_BLOCK = ("<!-- opsx-init:rules:start —— 由 opsx-project-init 维护，勿手改本区块 -->\n"
                     "旧内容\n<!-- opsx-init:rules:end -->\n")

    def test_old_idx_marker_block_replaced_not_duplicated(self, tmp_path):
        f = tmp_path / "INDEX.md"
        f.write_text("# 头\n\n" + self.OLD_IDX_BLOCK + "\n尾部用户内容\n", encoding="utf-8")
        init_mod.inject(str(f), *init_mod.MARK_IDX, "新内容")
        text = f.read_text(encoding="utf-8")
        assert text.count("opsx-init:rules:start") == 1   # 只有一个区块（替换，非追加）
        assert "新内容" in text and "旧内容" not in text
        assert "g-init 维护" in text                 # marker 文案已随替换更新
        assert "尾部用户内容" in text                     # 区块外内容无损


class TestRetiredHooks:
    """ADR-1（drop-per-dir-review-stub）：init.py 需能反注册退役的全局 hook。
    hook 安装本是「只增不减」——退役一个 hook 时，存量安装的 ~/.claude/settings.json
    会留孤儿注册 + ~/.claude/hooks/ 残留脚本，之后每次 Bash 触发失败 hook。
    retire_hooks() 在 init/update 每次跑时自愈：外科式摘 settings.json 条目 + 删脚本。"""

    RETIRED = "change-review-stub.py"  # 当前退役名单里的 hook

    def _settings(self, home):
        return home / "settings.json"

    def _make_home_with_retired(self, home):
        """构造一个「装过退役 hook」的存量 home：脚本 + settings 注册；另含一个无关 hook (ff0)。"""
        (home / "hooks").mkdir(parents=True)
        (home / "hooks" / self.RETIRED).write_text("print('stub')\n", encoding="utf-8")
        (home / "hooks" / "ff0-branch-guard.py").write_text("print('ff0')\n", encoding="utf-8")
        self._settings(home).write_text(json.dumps({
            "hooks": {
                "PreToolUse": [{"matcher": "Bash", "hooks": [
                    {"type": "command", "command": 'python3 "$HOME/.claude/hooks/ff0-branch-guard.py"'}
                ]}],
                "PostToolUse": [{"matcher": "Bash", "hooks": [
                    {"type": "command", "command": 'python3 "$HOME/.claude/hooks/change-review-stub.py"'}
                ]}],
            }
        }), encoding="utf-8")

    def test_retires_existing_registration_and_script_keeping_others(self, tmp_path, monkeypatch):
        home = tmp_path / "home"
        home.mkdir()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
        self._make_home_with_retired(home)

        init_mod.retire_hooks()

        # 脚本删除
        assert not (home / "hooks" / self.RETIRED).exists()
        # settings 里退役 hook 的注册被摘除
        data = json.loads(self._settings(home).read_text(encoding="utf-8"))
        blob = json.dumps(data)
        assert "change-review-stub.py" not in blob
        # 无关 hook (ff0) 与其脚本保留
        assert "ff0-branch-guard.py" in blob
        assert (home / "hooks" / "ff0-branch-guard.py").exists()

    def test_fresh_install_is_noop(self, tmp_path, monkeypatch):
        """从未装过退役 hook 的 fresh 安装：只有 ff0，retire 全 no-op、不误删、不崩。"""
        home = tmp_path / "home"
        (home / "hooks").mkdir(parents=True)
        (home / "hooks" / "ff0-branch-guard.py").write_text("print('ff0')\n", encoding="utf-8")
        self._settings(home).write_text(json.dumps({
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": 'python3 "$HOME/.claude/hooks/ff0-branch-guard.py"'}
            ]}]}
        }), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))

        init_mod.retire_hooks()  # 不抛

        assert (home / "hooks" / "ff0-branch-guard.py").exists()
        data = json.loads(self._settings(home).read_text(encoding="utf-8"))
        assert len(data["hooks"]["PreToolUse"]) == 1

    def test_no_settings_file_still_deletes_script(self, tmp_path, monkeypatch):
        """settings.json 不存在，但 hooks/ 里残留退役脚本 → 删脚本、不崩。"""
        home = tmp_path / "home"
        (home / "hooks").mkdir(parents=True)
        (home / "hooks" / self.RETIRED).write_text("print('stub')\n", encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))

        init_mod.retire_hooks()

        assert not (home / "hooks" / self.RETIRED).exists()

    def test_bad_json_settings_is_failsafe(self, tmp_path, monkeypatch):
        """settings.json 非法 JSON：反注册不崩（fail-safe），脚本删除照常进行。"""
        home = tmp_path / "home"
        (home / "hooks").mkdir(parents=True)
        (home / "hooks" / self.RETIRED).write_text("print('stub')\n", encoding="utf-8")
        self._settings(home).write_text("{ not valid json ", encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))

        init_mod.retire_hooks()  # 不抛

        assert not (home / "hooks" / self.RETIRED).exists()

    def test_multiple_registrations_all_removed(self, tmp_path, monkeypatch):
        """退役 hook 被误注册多条（多个 entry）→ 全部摘除。"""
        home = tmp_path / "home"
        (home / "hooks").mkdir(parents=True)
        (home / "hooks" / self.RETIRED).write_text("print('stub')\n", encoding="utf-8")
        self._settings(home).write_text(json.dumps({
            "hooks": {"PostToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": 'python3 "$HOME/.claude/hooks/change-review-stub.py"'}]},
                {"matcher": "Bash", "hooks": [{"type": "command", "command": 'python3 "$HOME/.claude/hooks/change-review-stub.py"'}]},
            ]}
        }), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))

        init_mod.retire_hooks()

        data = json.loads(self._settings(home).read_text(encoding="utf-8"))
        assert "change-review-stub.py" not in json.dumps(data)

    def test_malformed_non_dict_hook_element_does_not_crash(self, tmp_path, monkeypatch):
        """[impl-review-fix] CR-F1：hooks 列表混入非 dict truthy 元素（字符串等）时，
        反注册 MUST fail-safe 不抛（旧实现 `(h or {}).get` 会 AttributeError 冒穿崩 init/update）。"""
        home = tmp_path / "home"
        (home / "hooks").mkdir(parents=True)
        (home / "hooks" / self.RETIRED).write_text("print('stub')\n", encoding="utf-8")
        self._settings(home).write_text(json.dumps({
            "hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [
                "not-a-dict-entry",
                {"type": "command", "command": 'python3 "$HOME/.claude/hooks/change-review-stub.py"'},
            ]}]}
        }), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))

        init_mod.retire_hooks()  # 不抛

        data = json.loads(self._settings(home).read_text(encoding="utf-8"))
        blob = json.dumps(data)
        assert "change-review-stub.py" not in blob   # 退役项摘除
        assert "not-a-dict-entry" in blob            # 畸形非 dict 元素原样保留、未误删

    def test_non_string_command_does_not_crash(self, tmp_path, monkeypatch):
        """[impl-review-fix] CR-F1：command 字段是非字符串 truthy 值（如 int）时不得
        `TypeError`（`name not in 123` 崩溃）；应视为不匹配、原样保留。"""
        home = tmp_path / "home"
        (home / "hooks").mkdir(parents=True)
        (home / "hooks" / self.RETIRED).write_text("print('stub')\n", encoding="utf-8")
        self._settings(home).write_text(json.dumps({
            "hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": 123},
                {"type": "command", "command": 'python3 "$HOME/.claude/hooks/change-review-stub.py"'},
            ]}]}
        }), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))

        init_mod.retire_hooks()  # 不抛

        data = json.loads(self._settings(home).read_text(encoding="utf-8"))
        blob = json.dumps(data)
        assert "change-review-stub.py" not in blob   # 退役项摘除
        assert "123" in blob                         # 非 str command 条目原样保留

    def test_mixed_entry_keeps_sibling_hook(self, tmp_path, monkeypatch):
        """一个 matcher entry 内同时含退役 hook 与另一 hook → 只摘退役、保留兄弟、entry 不空则留。"""
        home = tmp_path / "home"
        (home / "hooks").mkdir(parents=True)
        (home / "hooks" / self.RETIRED).write_text("print('stub')\n", encoding="utf-8")
        self._settings(home).write_text(json.dumps({
            "hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": [
                {"type": "command", "command": 'python3 "$HOME/.claude/hooks/change-review-stub.py"'},
                {"type": "command", "command": 'python3 "$HOME/.claude/hooks/other-tool.py"'},
            ]}]}
        }), encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))

        init_mod.retire_hooks()

        data = json.loads(self._settings(home).read_text(encoding="utf-8"))
        blob = json.dumps(data)
        assert "change-review-stub.py" not in blob
        assert "other-tool.py" in blob


class TestRetireHooksCli:
    """T44: `init.py retire-hooks` 独立 mode——只调 retire_hooks()，不需 openspec/。"""

    def test_retire_hooks_mode_cleans_stale_hook(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"
        (home / "hooks").mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
        (home / "hooks" / "change-review-stub.py").write_text("# stale\n", encoding="utf-8")
        (home / "settings.json").write_text(json.dumps({"hooks": {"PostToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": 'python3 "$HOME/.claude/hooks/change-review-stub.py"'}]}
        ]}}), encoding="utf-8")
        monkeypatch.setattr(sys, "argv", ["init.py", "retire-hooks"])
        init_mod.main()
        assert not (home / "hooks" / "change-review-stub.py").exists()
        data = json.loads((home / "settings.json").read_text(encoding="utf-8"))
        assert data["hooks"]["PostToolUse"] == []
        assert "change-review-stub.py" in capsys.readouterr().out

    def test_retire_hooks_mode_needs_no_openspec(self, tmp_path, monkeypatch, capsys):
        home = tmp_path / "home"; home.mkdir()
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["init.py", "retire-hooks"])
        init_mod.main()
        assert "无退役 hook 残留" in capsys.readouterr().out

    def test_settings_write_is_atomic_no_tmp_residue(self, tmp_path, monkeypatch):
        home = tmp_path / "home"; (home / "hooks").mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
        settings = home / "settings.json"
        settings.write_text(json.dumps({"hooks": {"PostToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": 'python3 "$HOME/.claude/hooks/change-review-stub.py"'}]}
        ]}}), encoding="utf-8")
        assert init_mod._deregister_hook_in_settings(str(settings), "change-review-stub.py") is True
        json.loads(settings.read_text(encoding="utf-8"))   # 合法 JSON = 未撕裂
        assert list(home.glob("*.tmp")) == []              # 无 .tmp 残渣

    def test_deregister_write_failsafe_on_oserror(self, tmp_path, monkeypatch):
        # FB-3: 写路径 OSError（只读/满盘/权限）→ fail-safe 返回 False，不裸抛 traceback、不中断循环
        home = tmp_path / "home"; (home / "hooks").mkdir(parents=True)
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
        settings = home / "settings.json"
        settings.write_text(json.dumps({"hooks": {"PostToolUse": [
            {"matcher": "Bash", "hooks": [
                {"type": "command", "command": 'python3 "$HOME/.claude/hooks/change-review-stub.py"'}]}
        ]}}), encoding="utf-8")
        monkeypatch.setattr(init_mod.os, "replace",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("readonly")))
        assert init_mod._deregister_hook_in_settings(str(settings), "change-review-stub.py") is False


class TestAtomicWriteSettingsMkstemp:
    """T64: _atomic_write_settings() 改为 tempfile.mkstemp 唯一名。"""

    def test_tmp_file_uses_mkstemp_prefix(self, tmp_path, monkeypatch):
        settings = str(tmp_path / "settings.json")
        replaced_sources = []
        original_replace = os.replace
        def spy_replace(src, dst):
            replaced_sources.append(src)
            return original_replace(src, dst)
        monkeypatch.setattr(os, "replace", spy_replace)
        data = {"hooks": {}}
        assert init_mod._atomic_write_settings(settings, data) is True
        assert len(replaced_sources) == 1
        src_basename = os.path.basename(replaced_sources[0])
        assert src_basename.startswith(".settings-")
        with open(settings, encoding="utf-8") as f:
            written = json.load(f)
        assert written == data

    def test_mkstemp_oserror_returns_false(self, tmp_path, monkeypatch):
        import tempfile as tempfile_mod
        settings = str(tmp_path / "settings.json")
        monkeypatch.setattr(tempfile_mod, "mkstemp", lambda **kw: (_ for _ in ()).throw(OSError("disk full")))
        assert init_mod._atomic_write_settings(settings, {"x": 1}) is False


class TestEnsureGlobalHooksCodexWarning:
    """T6: ensure_global_hooks() Codex 降级告警。"""

    def test_codex_dir_present_shows_warning(self, tmp_path, monkeypatch):
        codex_home = tmp_path / ".codex"
        codex_home.mkdir()
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(codex_home) if p == "~/.codex" else os.path.expanduser.__wrapped__(p) if hasattr(os.path.expanduser, '__wrapped__') else str(tmp_path / p.replace("~/", "")))
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fake-claude"))
        # 先取真 isdir 再打补丁：原写法在 lambda 里再调被替换后的 os.path.isdir，会无限递归；
        # 只装一个 hook 时 makedirs 不走 isdir 分支所以没暴露，两个 hook 时第二次 makedirs 触发。
        real_isdir = os.path.isdir
        monkeypatch.setattr(os.path, "isdir", lambda p: True if p == str(codex_home) else real_isdir(p))
        output = init_mod.ensure_global_hooks()
        assert "⚠" in output
        assert "Codex" in output

    def test_codex_dir_absent_no_warning(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fake-claude"))
        monkeypatch.setattr(os.path, "expanduser", lambda p: str(tmp_path / "nonexistent") if p == "~/.codex" else str(tmp_path / p.replace("~/", "")))
        output = init_mod.ensure_global_hooks()
        assert "⚠" not in output


class TestAdrMigrationCheck:
    """AM-10 / 设计门 Q3：update 收尾的只读 ADR lint 提示（`init.py` 落点，C3 定位先例）。
    只读——不改任何文件，返回值不影响 update 的退出码。"""

    @staticmethod
    def _fake_adr_py(tmp_path, exitcode, stderr=""):
        script = tmp_path / "fake_adr.py"
        # 与真 adr.py 一样带 reconfigure 前导（仓内入口脚本的约定）：不带时 Windows 上
        # 管道的 stderr 走 cp1252 + backslashreplace，中文变成 \uXXXX 字面量。
        script.write_text(
            "import sys\n"
            "for _s in (sys.stdout, sys.stderr):\n"
            "    try: _s.reconfigure(encoding='utf-8', errors='replace')\n"
            "    except Exception: pass\n"
            f"sys.stderr.write({stderr!r})\n"
            f"sys.exit({exitcode})\n",
            encoding="utf-8",
        )
        return str(script)

    def test_no_adr_dir_skips(self, tmp_path):
        (tmp_path / "openspec").mkdir()
        assert init_mod.check_adr_migration(str(tmp_path)) == "openspec/adr/ 不存在，跳过 ADR 检查"

    def test_adr_py_not_installed(self, tmp_path, monkeypatch):
        (tmp_path / "openspec" / "adr").mkdir(parents=True)
        monkeypatch.setattr(init_mod, "_find_adr_py", lambda: None)
        assert init_mod.check_adr_migration(str(tmp_path)) == "g-adr 未安装，跳过 ADR 检查"

    def test_lint_clean_reports_green(self, tmp_path, monkeypatch):
        (tmp_path / "openspec" / "adr").mkdir(parents=True)
        fake = self._fake_adr_py(tmp_path, 0)
        monkeypatch.setattr(init_mod, "_find_adr_py", lambda: fake)
        assert init_mod.check_adr_migration(str(tmp_path)) == "ADR 格式检查：全绿"

    def test_lint_red_prompts_audit(self, tmp_path, monkeypatch):
        (tmp_path / "openspec" / "adr").mkdir(parents=True)
        fake = self._fake_adr_py(tmp_path, 1)
        monkeypatch.setattr(init_mod, "_find_adr_py", lambda: fake)
        assert init_mod.check_adr_migration(str(tmp_path)) == "ADR 格式未迁移，运行 `/g-adr audit`"

    def test_lint_usage_error_passes_through_stderr_verbatim(self, tmp_path, monkeypatch):
        # 设计要求「退出 2 则原样转述错误」——不额外包装我们自己的措辞
        msg = "adr: openspec/adr/x.md 不匹配 NNNN-<slug>.md；该目录只允许 ADR 文件"
        (tmp_path / "openspec" / "adr").mkdir(parents=True)
        fake = self._fake_adr_py(tmp_path, 2, stderr=msg)
        monkeypatch.setattr(init_mod, "_find_adr_py", lambda: fake)
        assert init_mod.check_adr_migration(str(tmp_path)) == msg

    def test_find_adr_py_respects_claude_config_dir(self, tmp_path, monkeypatch):
        home = tmp_path / "fake-claude"
        skill_dir = home / "skills" / "g-adr" / "scripts"
        skill_dir.mkdir(parents=True)
        adr_py = skill_dir / "adr.py"
        adr_py.write_text("", encoding="utf-8")
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home))
        assert init_mod._find_adr_py() == str(adr_py)

    def test_run_update_reports_adr_line_and_does_not_touch_files(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fake-claude"))
        proj = tmp_path / "proj"
        (proj / "openspec" / "adr").mkdir(parents=True)
        before = sorted((proj / "openspec" / "adr").iterdir())
        monkeypatch.setattr(init_mod, "_find_adr_py", lambda: None)
        init_mod.run(str(proj), "update")
        out = capsys.readouterr().out
        assert "g-adr 未安装，跳过 ADR 检查" in out
        assert sorted((proj / "openspec" / "adr").iterdir()) == before

    def test_run_init_mode_skips_adr_check(self, tmp_path, monkeypatch, capsys):
        # 落点仅 update 路径（设计门 Q3 拍板）：init 模式不跑该步
        monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "fake-claude"))
        called = []
        monkeypatch.setattr(init_mod, "check_adr_migration", lambda root: called.append(root) or "x")
        init_mod.run(str(tmp_path / "proj"), "init")
        assert called == []


@pytest.mark.skipif(os.name == "nt", reason="需要 POSIX 权限语义")
class TestSchemaSyncInPlace:
    """copy_bundle 的 schema 就地同步：覆盖沿用原 inode/mode，新建取 umask 默认，
    源里没有的旧条目删除，兄弟 schema 不动。"""

    @pytest.fixture
    def authority(self, tmp_path, monkeypatch):
        # 自备最小 schema 源；_validate_schema_authority 只看 schema.yaml 与其引用的模板
        src_schema = Path(init_mod.SCHEMAS_SRC) / init_mod.PROJECT_SCHEMA
        auth = tmp_path / "schema-authority"
        shutil.copytree(src_schema, auth / init_mod.PROJECT_SCHEMA)
        monkeypatch.setattr(init_mod, "SCHEMAS_SRC", str(auth))
        return auth / init_mod.PROJECT_SCHEMA

    def _dst(self, root):
        return root / "openspec" / "schemas" / init_mod.PROJECT_SCHEMA

    def test_existing_file_overwritten_in_place_keeps_inode_and_mode(self, tmp_path, authority):
        root = tmp_path / "project"
        copy_bundle(str(root))
        target = self._dst(root) / "schema.yaml"
        target.chmod(0o660)
        ino = target.stat().st_ino
        # 源文件 mode 与目标不同，且内容变了
        (authority / "schema.yaml").chmod(0o600)
        with open(authority / "schema.yaml", "a", encoding="utf-8") as f:
            f.write("\n# changed\n")

        copy_bundle(str(root))

        assert target.read_text(encoding="utf-8").endswith("# changed\n")
        assert target.stat().st_ino == ino
        assert (target.stat().st_mode & 0o777) == 0o660

    def test_stale_file_and_dir_removed(self, tmp_path, authority):
        root = tmp_path / "project"
        dst = self._dst(root)
        (dst / "old-dir").mkdir(parents=True)
        (dst / "old-dir" / "x.md").write_text("x", encoding="utf-8")
        (dst / "stale.txt").write_text("stale", encoding="utf-8")

        copy_bundle(str(root))

        assert not (dst / "stale.txt").exists()
        assert not (dst / "old-dir").exists()
        assert (dst / "schema.yaml").is_file()

    def test_new_files_and_dirs_follow_umask_not_source_mode(self, tmp_path, authority):
        root = tmp_path / "project"
        (authority / "schema.yaml").chmod(0o600)
        for d in authority.rglob("*"):
            if d.is_dir():
                d.chmod(0o700)
        old = os.umask(0o002)
        try:
            copy_bundle(str(root))
        finally:
            os.umask(old)
        dst = self._dst(root)
        assert (dst / "schema.yaml").stat().st_mode & 0o777 == 0o664
        subdirs = [d for d in dst.rglob("*") if d.is_dir()]
        assert subdirs, "schema 源应含 templates/ 子目录"
        assert all(d.stat().st_mode & 0o777 == 0o775 for d in subdirs)

    def test_sibling_schema_untouched(self, tmp_path, authority):
        root = tmp_path / "project"
        sibling = root / "openspec" / "schemas" / "consumer-owned"
        sibling.mkdir(parents=True)
        f = sibling / "schema.yaml"
        f.write_text("custom: true\n", encoding="utf-8")
        ino = f.stat().st_ino

        copy_bundle(str(root))

        assert f.read_text(encoding="utf-8") == "custom: true\n"
        assert f.stat().st_ino == ino


def test_g_schema_keeps_in_flight_sdflow_lock_working(tmp_path):
    directory = tmp_path / "openspec/changes/old-change"
    directory.mkdir(parents=True)
    (directory / "proposal.md").write_text("# existing change\n", encoding="utf-8")
    marker = directory / ".openspec.yaml"
    marker.write_text("schema: sdflow-spec-driven\n", encoding="utf-8")
    original = marker.read_bytes()
    assert init_mod.migrate_changes(str(tmp_path)) == 0
    copy_bundle(str(tmp_path))
    assert marker.read_bytes() == original
    assert (tmp_path / "openspec/schemas/g-spec-driven/schema.yaml").is_file()
    legacy = tmp_path / "openspec/schemas/sdflow-spec-driven/schema.yaml"
    text = legacy.read_text(encoding="utf-8")
    assert "name: sdflow-spec-driven" in text and "/g-spec" in text
    assert "/sdflow-spec" not in text
