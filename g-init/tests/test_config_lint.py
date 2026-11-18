"""config-lint（mlh-p3-determ-guards Task 2）：openspec/config.yaml 结构 fail-closed 校验门。
只校验结构（顶层键不重复 / schema 顶层键存在 / rules 四子键 / metrics.enabled 布尔），
不碰内容文案。手写 stdlib 行扫描（follow anchor_lint.py::read_metrics_enabled 范式，不 import yaml）。
可选顶层块（metrics）缺失一律条件化放行（防 mlh-p2 假阳，见 memory
dogfood-blind-spot-source-config）。
已退役的 model-tiers / effort-tiers 不再校验（残留块被忽略）。

Run: python -m pytest g-init/tests/test_config_lint.py -v
"""
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


REPO_ROOT = Path(__file__).parent.parent.parent

# 【发布 clone 边界】本门读本仓 `openspec/` 当被测语料，发布用 public clone 不含它。
# 完整仓里照跑照红；缺 `openspec/` 时显式 skip 并说明——MUST NOT 静默 pass。
_HAS_OPENSPEC = (REPO_ROOT / "openspec").is_dir()
needs_full_repo = pytest.mark.skipif(not _HAS_OPENSPEC, reason="本门的被测语料是本仓 openspec/ 台账；发布 clone 不含 openspec/")
INIT_PY = Path(__file__).parent.parent / "scripts" / "init.py"


def _write_config(root: Path, content: str):
    osdir = root / "openspec"
    osdir.mkdir(parents=True, exist_ok=True)
    (osdir / "config.yaml").write_text(content, encoding="utf-8")


def _run_lint(root):
    return subprocess.run(
        [sys.executable, str(INIT_PY), "config-lint", "--root", str(root)],
        capture_output=True, text=True,

        encoding="utf-8",
        errors="replace",)


VALID_RULES_BLOCK = """schema: spec-driven
rules:
  proposal:
    - a
  specs:
    - b
  design:
    - c
  tasks:
    - d
"""


class TestConfigLintBadStructure:
    def test_missing_schema_and_rules_nonzero_with_reason(self, tmp_path):
        _write_config(tmp_path, "foo: bar\n")
        r = _run_lint(tmp_path)
        assert r.returncode != 0
        assert "schema" in r.stderr
        assert "rules" in r.stderr


class TestConfigLintMissingRuleSubkey:
    def test_missing_rules_proposal_nonzero(self, tmp_path):
        _write_config(tmp_path, """schema: spec-driven
rules:
  specs:
    - b
  design:
    - c
  tasks:
    - d
""")
        r = _run_lint(tmp_path)
        assert r.returncode != 0
        assert "proposal" in r.stderr


class TestConfigLintWholeDocumentParseFailure:
    """yq 是真 YAML 解析器：mapping 上下文里的裸标量行（漏冒号笔误）是**语法级非法 YAML**
    （`mapping values are not allowed in this context`），会让**整份 config.yaml** 解析失败——
    不再有旧版行扫描器那种「局部容错、后续叶子仍被校验」。这是 yq 委托的既定代价
    （spec-review F9/decision-memo：诊断精度下降换取「不手搓 YAML 解析器」）。"""

    def test_missing_colon_leaf_is_a_whole_document_parse_failure(self, tmp_path):
        """漏冒号叶子行 MUST 被判定整份文档语法错误（非零退出 + 通用「解析失败」reason），
        MUST NOT 静默放行。"""
        _write_config(tmp_path, VALID_RULES_BLOCK + """metrics:
  enabled true
  extra: 1
""")
        r = _run_lint(tmp_path)
        assert r.returncode != 0
        assert "解析失败" in r.stderr, r.stderr


class TestConfigLintRetiredTierBlocks:
    """model-tiers / effort-tiers 已随 fan-out 架构退役：存量 config 里残留（哪怕内容早已不合
    旧校验）也只被忽略，不得让 config-lint 报违规——g-init 第二步要求 lint 必须通过。"""

    def test_leftover_tier_blocks_are_ignored(self, tmp_path):
        _write_config(tmp_path, VALID_RULES_BLOCK + """model-tiers:
  claude:
    strong: "bad value; rm -rf"
effort-tiers:
  strong: ultra
""")
        r = _run_lint(tmp_path)
        assert r.returncode == 0, r.stderr


class TestConfigLintMetrics:
    def test_metrics_enabled_non_bool_nonzero(self, tmp_path):
        _write_config(tmp_path, VALID_RULES_BLOCK + """metrics:
  enabled: yes-please
""")
        r = _run_lint(tmp_path)
        assert r.returncode != 0
        assert "metrics" in r.stderr
        assert "enabled" in r.stderr

    def test_no_metrics_block_passes_consumer_style_fixture(self, tmp_path):
        """mlh-p2 假阳防护（M3）：消费仓风格 config——metrics 块整段不存在（g-init update
        从不注入新顶层键，故 100% 存量消费仓无 metrics 块）→ 必须放行 exit 0，不得裸
        KeyError/误判违规。"""
        _write_config(tmp_path, """schema: spec-driven
context: |
  ## 本项目
  consumer repo, unrelated tech stack context prose.
""" + VALID_RULES_BLOCK.split("\n", 1)[1])
        r = _run_lint(tmp_path)
        assert r.returncode == 0, r.stderr


class TestConfigLintRegressionBaseline:
    @needs_full_repo
    def test_real_repo_config_yaml_passes(self):
        """回归基线：本仓真实 openspec/config.yaml（含 metrics: enabled: true，注释掉的
        model-tiers）必须 lint 通过。"""
        r = _run_lint(REPO_ROOT)
        assert r.returncode == 0, r.stderr


class TestConfigLintEncodingError:
    """[impl-review-fix] F2：`lint_config` 此前只 `except OSError`——非 UTF-8 config.yaml
    会让 `f.read()` 抛 `UnicodeDecodeError`，未被捕获、以裸 traceback 崩溃（不是干净的
    reason + 非零退出）。补捕获 `UnicodeDecodeError`，与 anchor_lint.py 的既有范式
    （read_metrics_enabled / load_enums 同款 `except (OSError, UnicodeDecodeError)`）对齐。"""

    def test_non_utf8_config_yaml_clean_reason_nonzero(self, tmp_path):
        osdir = tmp_path / "openspec"
        osdir.mkdir(parents=True)
        (osdir / "config.yaml").write_bytes(
            b"schema: spec-driven\nrules:\n  proposal:\n\xff\xfe bad bytes here \n"
        )
        r = _run_lint(tmp_path)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        assert "config.yaml" in r.stderr


class TestConfigLintMissingFile:
    """补测（minor polish）：config.yaml 整个文件不存在（连 openspec/ 目录都没有）时，
    `lint_config` 走 `except OSError` 分支报干净 reason + 非零退出，不裸 KeyError/FileNotFoundError。"""

    def test_missing_config_yaml_clean_reason_nonzero(self, tmp_path):
        r = _run_lint(tmp_path)
        assert r.returncode != 0
        assert "Traceback" not in r.stderr
        assert "config.yaml" in r.stderr


class TestConfigLintGitRootAutoProbe:
    """补测（minor polish）：`--root` 省略时走 `_git_root_or_dot()` 自动探测 git 仓根——
    在本仓任意子目录下裸跑 `config-lint`（不传 --root）应能探到仓根并 lint 通过（本仓
    真实 config.yaml 干净）。"""

    @needs_full_repo
    def test_no_root_flag_probes_git_root(self):
        r = subprocess.run(
            [sys.executable, str(INIT_PY), "config-lint"],
            capture_output=True, text=True, cwd=str(REPO_ROOT / "g-init"),

            encoding="utf-8",
            errors="replace",)
        assert r.returncode == 0, r.stderr


class TestYqWrapper:
    """直测 `_yq()`/`_check_yq()` 本体（shared-yaml-subset-parser Task 4）——config-lint 的
    CLI 断言只能间接观察 yq 委托的效果，这里直接锁住薄封装自身的关键契约：default 分支、
    非零退出 raise、未安装/非 mikefarah 时 fail-loud，与 anchor_lint.py 已落地的同类用例
    对齐（design.md §1 参考实现的核验面）。"""

    def _mod(self):
        """每次都用一个独立的模块实例，避免 `_yq_bin` 进程内缓存跨用例互相污染
        （同 anchor_lint.py 的 test_anchor_lint.py 既有范式）。"""
        import importlib
        import init as init_mod_local
        return importlib.reload(init_mod_local)

    def test_yq_default_for_missing_key(self, tmp_path):
        mod = self._mod()
        cfg = tmp_path / "x.yaml"
        cfg.write_text("schema: spec-driven\n", encoding="utf-8")
        assert mod._yq(".nope", str(cfg), default="fallback") == "fallback"

    def test_yq_reads_typed_value(self, tmp_path):
        mod = self._mod()
        cfg = tmp_path / "x.yaml"
        cfg.write_text("metrics:\n  enabled: true\n", encoding="utf-8")
        assert mod._yq(".metrics.enabled", str(cfg)) is True

    def test_yq_raises_on_nonzero_exit(self, tmp_path):
        mod = self._mod()
        cfg = tmp_path / "bad.yaml"
        cfg.write_text('key: "unterminated\n', encoding="utf-8")
        with pytest.raises(RuntimeError):
            mod._yq(".", str(cfg))

    def test_yq_not_installed_raises(self, tmp_path, monkeypatch):
        mod = self._mod()
        monkeypatch.setattr(mod.shutil, "which", lambda name: None)
        cfg = tmp_path / "x.yaml"
        cfg.write_text("schema: spec-driven\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="未安装"):
            mod._yq(".schema", str(cfg))

    def test_yq_identity_check_rejects_non_mikefarah(self, tmp_path, monkeypatch):
        mod = self._mod()
        monkeypatch.setattr(mod.shutil, "which", lambda name: "/usr/bin/yq")

        class FakeProc:
            stdout = "yq 2.x (kislyuk/yq)\n"
            stderr = ""
            returncode = 0

        monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: FakeProc())
        cfg = tmp_path / "x.yaml"
        cfg.write_text("schema: spec-driven\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="mikefarah"):
            mod._yq(".schema", str(cfg))

    def test_check_yq_not_installed_returns_reason_not_raise(self, monkeypatch):
        mod = self._mod()
        monkeypatch.setattr(mod.shutil, "which", lambda name: None)
        ok, reason = mod._check_yq()
        assert ok is False
        assert "未安装" in reason

    def test_check_yq_ok_when_available(self):
        mod = self._mod()
        ok, reason = mod._check_yq()
        assert ok is True
        assert reason is None

    def test_lint_config_reports_reason_when_yq_missing(self, tmp_path, monkeypatch):
        """`lint_config` 的入口门（`_check_yq()`）在 yq 不可用时返回 reason 列表，不崩溃/
        不退出——这是它与 `run()` 路径（靠既有 `except RuntimeError: _die()` 兜底）的
        唯一差异化处理，见 `_check_yq()` docstring。"""
        mod = self._mod()
        monkeypatch.setattr(mod.shutil, "which", lambda name: None)
        osdir = tmp_path / "openspec"
        osdir.mkdir(parents=True)
        (osdir / "config.yaml").write_text("schema: spec-driven\n", encoding="utf-8")
        reasons = mod.lint_config(str(tmp_path))
        assert len(reasons) == 1
        assert "未安装" in reasons[0]


class TestConfigLintCliSmoke:
    """adv-A 爆点2：config-lint 加进 mode choices 后，既有 3 个 mode（init/update/
    retire-hooks）的 argparse 解析 + 实际执行不受扰动（未误引入 add_subparsers 重构）。"""

    def test_existing_modes_still_run(self, tmp_path):
        env = dict(os.environ)
        env["CLAUDE_CONFIG_DIR"] = str(tmp_path / "fake-claude")
        project = tmp_path / "proj"
        project.mkdir()

        r_init = subprocess.run(
            [sys.executable, str(INIT_PY), "init", "--root", str(project)],
            capture_output=True, text=True, env=env,

            encoding="utf-8",
            errors="replace",)
        assert r_init.returncode == 0, r_init.stderr
        assert (project / "openspec" / "config.yaml").is_file()

        r_update = subprocess.run(
            [sys.executable, str(INIT_PY), "update", "--root", str(project)],
            capture_output=True, text=True, env=env,

            encoding="utf-8",
            errors="replace",)
        assert r_update.returncode == 0, r_update.stderr

        r_retire = subprocess.run(
            [sys.executable, str(INIT_PY), "retire-hooks"],
            capture_output=True, text=True, env=env,

            encoding="utf-8",
            errors="replace",)
        assert r_retire.returncode == 0, r_retire.stderr


class TestDuplicateTopKeys:
    """T149: lint_config() 顶层重复键检测。"""

    def test_duplicate_top_key_detected(self, tmp_path):
        _write_config(tmp_path, "schema: spec-driven\nrules:\n  proposal:\n    - a\n  specs:\n    - b\n  design:\n    - c\n  tasks:\n    - d\nschema: other\n")
        r = _run_lint(tmp_path)
        assert r.returncode != 0
        assert "重复" in r.stderr

    def test_no_duplicate_passes(self, tmp_path):
        _write_config(tmp_path, VALID_RULES_BLOCK)
        r = _run_lint(tmp_path)
        assert r.returncode == 0, r.stderr

    def test_non_utf8_no_crash(self, tmp_path):
        osdir = tmp_path / "openspec"
        osdir.mkdir(parents=True)
        (osdir / "config.yaml").write_bytes(b"\xff\xfe invalid utf8\n")
        r = _run_lint(tmp_path)
        assert "Traceback" not in r.stderr

    def test_bom_first_key_detected(self, tmp_path):
        osdir = tmp_path / "openspec"
        osdir.mkdir(parents=True)
        content = "schema: spec-driven\nrules:\n  proposal:\n    - a\n  specs:\n    - b\n  design:\n    - c\n  tasks:\n    - d\nschema: other\n"
        (osdir / "config.yaml").write_text(content, encoding="utf-8-sig")
        r = _run_lint(tmp_path)
        assert r.returncode != 0
        assert "重复" in r.stderr
