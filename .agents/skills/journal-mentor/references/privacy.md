# 当前会话隔离

真实日记接入需要已核实当前会话不使用、不贡献 Codex 跨会话记忆。文件放在项目内不是此条件的证明。

## 可用入口

推荐从本项目根目录运行 `./start-mentor.ps1`，使用已安装的 Codex CLI 开始**新**会话。脚本传入：

```text
-c features.memories=false
-c features.external_agent_memory_import=false
-c memories.generate_memories=false
-c memories.use_memories=false
```

这些参数只对本次启动生效，不改用户全局配置。入口不支持附加任意配置覆盖或恢复旧会话。`-CheckOnly` 只验证功能标志，不发起模型请求、不读取日记；不能用它证明另一个桌面会话已隔离。

桌面使用：将本目录作为项目打开，在新会话中使用技能；核实客户端可用的会话记忆控制，确保不读取已有通用记忆且不用于生成后续通用记忆。官方说明中的 `/memories` 适用于支持该命令的客户端。不要假定所有桌面版本都有相同入口。若无法核实，使用上面的 CLI 入口。

`.codex/config.toml` 设置相同默认值，仅在项目配置被信任、实际加载且没有更高优先级覆盖时有效。读取该文件只能证明配置意图，不能证明正在运行的会话状态。已经运行的会话不会因新增文件而自动完成隔离。

## 执行约束

核实后，调用辅助脚本时使用 `--session-isolated`，表示执行者已经做了此检查；脚本自身不能控制或证明宿主记忆开关。每个新会话重新核实，不在磁盘保存永久“已批准”标记。

所有个人派生数据只写到本项目的 `memory/` 和 `reviews/`；日记只在 `diary/`。不能读取父目录日记、其他项目、账号历史来补充画像。必要的新增来源由用户明确指定，并重新确认边界。

此方案是项目作用域及宿主配置隔离，不是加密容器、操作系统权限隔离或服务端零留存。使用前应了解并接受所选在线服务的会话处理与保留方式。不要擅自修改账号数据控制，也不要承诺能清除平台记录。把包含日记的旧会话带到另一个项目，不会自动清除旧上下文；需要使用新会话。

官方依据（实现时核对）：
- https://learn.chatgpt.com/docs/customization/memories
- https://learn.chatgpt.com/docs/config-file/config-reference
- https://learn.chatgpt.com/docs/build-skills
