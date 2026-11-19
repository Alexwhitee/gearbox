"""隔离 HOME 的子进程环境：供真跑 setup.sh / init.py 的测试使用。"""

from __future__ import annotations

import os


def isolated_home_env(home: str | os.PathLike[str], base=None) -> dict[str, str]:
    """复制 base（缺省 os.environ），把 HOME / USERPROFILE 指向 home，并去掉会把落点引出假 HOME 的变量。

    - G_HOME：install_g 的 ~/.g 落点覆写。
    - CLAUDE_CONFIG_DIR：setup.sh 的 Claude skills/agents 落点与 init.py 的全局 hook 落点都优先读它；
      开发机上它常指向用户真实的配置目录，只改 HOME 挡不住，测试会写进真实配置。
    - USERPROFILE：Windows 上 Python 的 expanduser（init.py retire-hooks 的缺省落点）读它而不读 HOME。
    """
    env = dict(os.environ if base is None else base)
    env["HOME"] = str(home)
    env["USERPROFILE"] = str(home)
    env.pop("G_HOME", None)
    env.pop("CLAUDE_CONFIG_DIR", None)
    return env
