# 协作约定（三人小组 · 联调期必读）

## 分支与提交

- `main` 只放可运行版本；A/B 各自开 feature 分支：`feat/a-xxx`、`feat/b-xxx`，完成后提 PR，由 C 审合并。
- commit 用约定式前缀：`feat:` 新功能、`fix:` 修 bug、`docs:` 文档、`test:` 测试、`chore:` 杂项。
  例：`fix(agent): 步数耗尽时返回空回复`。
- 一个 PR 只做一件事，附带「怎么验证」一句话（命令或操作步骤）。

## 改接口的顺序（防止联调打架）

1. 先改 `INTERFACE.md`（签名 / 返回格式 / 环境变量）。
2. 群里 @另外两人确认。
3. 再改代码，并同步更新受影响的测试与文档。

## 合并前自检（本地 1 分钟）

```bash
run.ps1 test                 # Windows（内置环境）
# 或
python tests/selftest.py
python tests/test_static_checks.py
python tests/test_mcp_integration.py
python tests/test_agent_loop_mock.py
python tests/test_task_views.py
python tests/test_e2e.py
python tests/test_ui_smoke.py
```

全绿才合并；红了在 `demo/bug_log.md` 登记，@对应的人修。

## 安全红线

- `.env`、真实 API key、个人数据 `.db` 一律不提交（见 `.gitignore`）。
- 不在 issue / PR / 博客里贴完整密钥；泄露了立刻去平台吊销重建。
- 演示数据用假数据，别把真实课程表/成绩单导进去。

## 文档归属

| 文档 | 负责人 |
|---|---|
| `INTERFACE.md`、`交付清单.md`、`README.md` | C |
| `docs/环境配置.md` | C（A 提供后端细节） |
| `demo/bug_log.md` | C 记录，A/B 修复后回填 |
| `blog/博客园随笔.md` | C 统稿，A/B 交心得 |
