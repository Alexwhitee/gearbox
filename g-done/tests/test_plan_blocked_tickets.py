"""plan_blocked_tickets：tickets.md 中 `BLOCKED: <原因>` 停点行的共享解析（gate 与 impl_route frontier 同源）。"""
import sys
from pathlib import Path

_scripts_path = str(Path(__file__).parent.parent / "scripts")
if _scripts_path not in sys.path:
    sys.path.insert(0, _scripts_path)

import ship_gate as sg  # noqa: E402

PLAN = """# Tickets

BLOCKED: 前言段的行不归任何票

### Task 1: a

**Blocked-by:** none
**R-ID:** 1.1

- [x] done

### Task 2: b

**Blocked-by:** 1
**R-ID:** 1.2

- [ ] todo
BLOCKED: 测试环境缺数据库

### Task 3: c

**Blocked-by:** 1
- **BLOCKED**：上游接口未定

```
### Task 9: fenced
BLOCKED: fenced 示例不算
```

### Task 4: 实现验证

**Blocked-by:** 1,2,3
**R-ID:** all
"""


def test_blocked_lines_are_attributed_to_their_ticket():
    assert sg.plan_blocked_tickets(PLAN) == {"2": "测试环境缺数据库", "3": "上游接口未定"}


def test_no_blocked_lines_returns_empty():
    assert sg.plan_blocked_tickets("### Task 1: a\n\n- [ ] x\n") == {}


def test_blocked_without_reason_still_counts():
    assert sg.plan_blocked_tickets("### Task 1: a\nBLOCKED:\n") == {"1": "（未写原因）"}
