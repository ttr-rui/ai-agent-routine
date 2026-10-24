"""零依赖自检：不想装 pytest 时，直接 `python tests/selftest.py` 也能验证数据层。

装了 pytest 的小组用 `pytest -q`（用例是同一批，见 test_storage.py）。
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))

from test_storage import (  # noqa: E402
    test_add_and_get,
    test_list_filter,
    test_update_complete_delete,
    test_stats_and_briefing,
    test_batch_add,
    test_duplicate_add,
    test_memory,
)

CASES = [
    test_add_and_get,
    test_list_filter,
    test_update_complete_delete,
    test_stats_and_briefing,
    test_batch_add,
    test_duplicate_add,
    test_memory,
]


def main() -> int:
    ok = 0
    for case in CASES:
        # 用 mkdtemp 而非 TemporaryDirectory：Windows 下 SQLite 句柄未释放会删不掉临时目录
        tmp = tempfile.mkdtemp(prefix="taskmate_test_")
        try:
            case(Path(tmp))  # pytest 传入的是 pathlib.Path，这里保持一致
            print(f"  PASS  {case.__name__}")
            ok += 1
        except AssertionError as e:
            print(f"  FAIL  {case.__name__}: {e}")
        except Exception as e:
            print(f"  ERROR {case.__name__}: {type(e).__name__}: {e}")
        finally:
            import shutil

            shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{ok}/{len(CASES)} 通过")
    return 0 if ok == len(CASES) else 1


if __name__ == "__main__":
    sys.exit(main())
