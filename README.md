# Journal Mentor · 日记复盘导师

A project-scoped Codex skill for evidence-linked journal reflection and correctable local memory.

读取本地 Markdown 日记，结合项目内历史分析情绪与压力、职业变化、思维偏差与重复行为。先给观察，必要时交流，再形成建议与复盘；原文保持只读。

## 能做什么

- 手动复盘：首次默认最近 7 天，之后增量读取，也可指定日期范围。
- 长期记忆：事件、当前阶段、目标、待验证假设和已采纳行动分别记录，保留原文出处与版本。
- 纠错：日记修改后，相关记忆失效；更新认识并撤回依赖旧判断的报告。
- 行动跟进：区分提出、采纳、尝试和完成，不把未回应当成没做。
- 项目作用域：技能与数据保留在一个项目内，不依赖全局个人记忆。

不默认给人格或人生打分，不做心理诊断，不把短期情绪固化成性格标签。它是反思辅助工具，输出需要结合事实与个人判断核对。

## 快速开始

需要 Python 3.10+、已安装并登录的 Codex CLI。Python 辅助脚本仅使用标准库；AI 分析由当前 Codex 会话完成，仍受账号用量与服务条款约束。

```powershell
git clone https://github.com/cafflai/journal-mentor.git
cd journal-mentor
New-Item -ItemType Directory -Force diary | Out-Null
```

把准备复盘的 UTF-8 Markdown 文件放入 `diary/`，然后在 Windows PowerShell 中启动新的隔离会话：

```powershell
.\start-mentor.ps1
```

也可以把仓库作为 Codex 项目打开，核实当前会话的记忆控制后调用 `$journal-mentor`。若桌面版本无法核实，不要仅凭配置文件存在就读取私密日记。

macOS/Linux 可从仓库根目录使用同样的显式配置启动新会话：

```sh
codex -C . \
  -c features.memories=false \
  -c features.external_agent_memory_import=false \
  -c memories.generate_memories=false \
  -c memories.use_memories=false \
  '使用 $journal-mentor 复盘最近的日记。此新会话已通过四项显式覆盖禁用通用记忆；只使用本项目资料。'
```

这些设置依赖所用 Codex 版本的支持。项目中的诊断命令可核对实际配置；它不能证明另一个已经运行的会话状态。

### 日记格式

一个文件对应一个记录日期，文件名包含 `YYYY-MM-DD`，例如 `2026-01-15.md`。或者使用顶部字段：

```markdown
---
date: 2026-01-15
---
这里写当天的记录。
```

日期不明或冲突时会要求明确指定。当前不自动将一个文件里的多日日记精确拆分。日期窗口默认使用 UTC+08:00（Asia/Shanghai）。

### 可以这样交流

- “复盘最近的日记，先告诉我你观察到了什么。”
- “这次先理解压力来源，不急着列行动清单。”
- “我的阶段变了，请修正之前的认识。”
- “哪些结论有依据，哪些只是你的猜测？”
- “忘记这个判断，并说明会影响哪些记录。”

## 数据与隐私

运行时的数据目录为：

```text
diary/                 原日记，只读
memory/store.json      项目记忆、证据和处理进度
memory/pending.json    未完成批次
memory/draft.json      交流后准备保存的草稿
reviews/               完成的 Markdown 复盘
```

这些目录、测试临时目录、日志、环境文件和常见密钥文件均被 `.gitignore` 排除。本仓库不包含真实日记、个人画像、复盘或历史会话。测试中的文本均为虚构。

**本地保存不等于离线处理或服务端零留存。** 日记内容在分析时会进入当前在线模型会话。启动器只对本次启动覆盖 Codex 的通用记忆设置，不改变账号数据保留政策，不删除会话历史，也不提供加密或操作系统级隔离。`.gitignore` 不能阻止强制提交或其他软件同步数据。

`--session-isolated` 只是辅助脚本调用者的核实声明，不是关闭平台记忆的开关。详细说明见 [隐私边界](.agents/skills/journal-mentor/references/privacy.md)。

## 开发与验证

运行虚构数据测试，不需要模型调用或真实日记：

```sh
python -X utf8 -B -m unittest discover -s tests -v
```

已安装 Codex CLI 时，可以只读核实配置与技能发现；此命令不启动 AI turn：

```sh
python -X utf8 -B tests/check_codex.py --launcher
```

测试覆盖增量读取、版本失效、纠错、日期覆盖、原文只读、路径越界、项目存储隔离、遗忘、行动采纳与导出恢复。它们不证明模型结论正确，也不保证长期建议效果。

实现细节见 [技能入口](.agents/skills/journal-mentor/SKILL.md) 和 [工作流与记忆格式](.agents/skills/journal-mentor/references/workflow.md)。

## 已知限制

- 以整份文件校验版本，修改一处可能要求复查多条关联记忆。
- 旧复盘依赖关系采取保守策略，纠正一条记忆可能撤回整份旧报告。
- 不内置定时任务、独立日记应用、向量数据库或跨项目共享画像。
- 路径检查不能抵御可同时篡改项目与宿主配置的本地程序。

## 贡献与许可

欢迎通过 Issue 或 Pull Request 提出问题、改进代码。请只使用最小化的虚构样例；不要上传真实日记、记忆、报告、凭据或带私人路径的完整日志。

采用 [MIT License](LICENSE)。
