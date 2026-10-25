# 辅助脚本与记忆格式

在项目根目录执行，脚本路径记为 `.agents/skills/journal-mentor/scripts/journal.py`。使用 `python -X utf8`；以下命令里的 `SCRIPT` 替换为这个路径。只有核实当前会话隔离后才加 `--session-isolated`。

```text
python -X utf8 SCRIPT collect --session-isolated
python -X utf8 SCRIPT collect --session-isolated --start 2026-10-01 --end 2026-10-14
python -X utf8 SCRIPT collect --session-isolated --date notes.md=2026-10-14
python -X utf8 SCRIPT recall --session-isolated
python -X utf8 SCRIPT finish --session-isolated
python -X utf8 SCRIPT amend --session-isolated
python -X utf8 SCRIPT forget --session-isolated --id pattern-001
python -X utf8 SCRIPT forget --session-isolated --id pattern-001 --apply
```

首次最近 7 天，包含今天；默认时区 Asia/Shanghai。工具也支持 `--today YYYY-MM-DD` 用于复现或虚构测试。`--start` 和 `--end` 均包含边界。指定范围不改变默认增量游标，避免一次历史补录/跳跃复盘跳过其他记录。

每个 Markdown 文件表示一个记录日期。支持文件名中的 `YYYY-MM-DD`（例如 `2026-10-14记.md`），或文件顶部 YAML 的 `date: YYYY-MM-DD`。两者冲突或日期缺失时返回问题，使用 `--date 相对于diary的文件路径=日期` 显式解决。一个文件包含多个日期时，先请用户确认覆盖日期和读取范围，不冒充已支持逐段日期解析。

`collect` 返回：读取范围、新增/修订原文、未知日期文件、记录缺口、有效项目记忆、失效记录 id。所有输出视为私密材料。它在 `memory/pending.json` 保存源文件指纹和开始时的存储修订号，不保存原文副本。无新内容且无待修正记忆时不建立新批次。有未完成批次时保留它，不静默覆盖；需重建时使用 `--replace-pending`，旧草稿会清除。明确指定的文件日期在完成复盘后保留，后续可再次覆盖更正。

## 保存一个完成的复盘

把下列 JSON 写入 `memory/draft.json`，随后执行 `finish`。`review` 是自然中文 Markdown，不要求展示机器字段。`records` 是新增或更新的条目，未出现的现有条目保留。

```json
{
  "review": "# 近期复盘\n\n结合 diary/2026-10-14.md 的记录……",
  "records": [
    {
      "id": "stage-001",
      "kind": "stage",
      "text": "用户明确表示开始求职。",
      "status": "active",
      "current": true,
      "sources": [{"path": "diary/2026-10-14.md", "date": "2026-10-14", "sha256": "复制 collect 的 sha256"}],
      "discussion": []
    },
    {
      "id": "pattern-001",
      "kind": "hypothesis",
      "text": "在目标不明确时，可能倾向反复准备以延迟决策；需要更多事件验证。",
      "status": "tentative",
      "sources": [{"path": "diary/2026-10-14.md", "date": "2026-10-14", "sha256": "复制 collect 的 sha256"}],
      "alternatives": ["也可能是外部信息不足"],
      "counterevidence": [],
      "discussion": []
    }
  ]
}
```

字段：
- `id`：小写字母、数字、连字符，稳定唯一。更新时沿用。重复内容和相同证据不会因换 id 获得额外支持。
- `kind`：`fact`、`stage`、`goal`、`hypothesis`、`action`、`correction`。
- `status`：普通条目 `active` / `historical` / `retracted`；假设 `tentative` / `rejected` / `retracted`，不能保存成已证实的人格判断；行动 `proposed` / `accepted` / `tried` / `completed` / `dropped`。
- `sources`：直接原文路径、日期、散列值，不能把其他总结当原始证据。文件必须处于本项目 `diary/`，且对应版本仍存在。用于支持判断的反例也纳入来源。
- `discussion`：本次用户的明确补充，格式 `{"date":"2026-10-14","quote":"用户明确说的话"}`。允许没有日记来源的当前目标或纠正，但必须有用户原话；不能伪造确认。脚本只校验结构，不能证明原话真实。
- 已采纳/尝试/完成/放弃的行动需要 `adoption: {"date":"YYYY-MM-DD","quote":"用户明确采纳时的原话"}`。只有用户在日记中明确作出的决定也可作为依据，注明来源。
- `current`：当前背景/阶段使用；过往阶段置为 `false`，不要让新旧阶段并列代表现在。
- 可选 `alternatives`、`counterevidence`：解释与反例。合理的非职业状态可以同时存在，不强制一个阶段枚举。

脚本校验路径、源版本、日期、结构和采纳字段，但不代替模型对证据是否支持结论的判断。完成前逐条核对。

`finish` 拒绝源文件在交流期间变化、存储被另一操作更改、未处理的失效记忆，以及重复完成。权威存储为 `memory/store.json`；`reviews/*.md` 从中导出。先原子更新权威存储，再导出报告，导出失败可用 `export --session-isolated` 修复。未完成批次不推进游标。修订历史来源会将相关旧报告撤回，防止它继续被当作有效复盘。

## 没有新日记时修正记忆

`recall` 先验证已有来源并返回有效条目与失效 id，不把失效条目当作当前事实。需要修正时仍写 `memory/draft.json`，包含 `records` 与 `base_revision`（取自 `recall`），然后执行 `amend`。该操作不推进日记游标，不需要伪造新日记。修改已有记录会撤回依赖旧记录的历史报告，避免旧结论重新污染上下文。

## 忘记

`forget` 默认预览，`--apply` 才修改。删除指定条目，保留不含内容的 id 墓碑防止原 id 意外复活；撤回依赖它的报告正文，删除未完成草稿和批次。报告正文存储和导出副本都撤回，原文不变。它无法阻止模型从仍然存在的原文再次提出类似解释；如用户要求，另记录最小化、不重存敏感细节的纠错规则。平台会话历史不在操作范围。
