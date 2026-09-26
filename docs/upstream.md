# 上游来源与复用边界

- 来源：https://github.com/jev-chat/jev-chat-jarvis-mac
- 固定标签：`v0.5.0`
- 固定提交：`5814df87cf2a6f6b3210208d8afdb62ce6f5f386`
- 核验日期：2026-09-24；独立临时克隆的 HEAD 与计划一致。
- `LICENSE`：本项目以 MIT 发布，新增实现署名为 ai-freer；保留上游 MIT 授权文本及 eatmoreduck 原版权声明。
- `pyproject.toml`：仅选择上游的 ApplicationServices 和 Cocoa 依赖及最低版本，供后续 AX 与悬浮窗使用。
- `judge_jev.py` / `judge.py`：参考 System One 的 choice/score 请求形状及意图、风险标签；在 `jev.py` 中重新实现，全局 Jev 设置关闭时不发起请求。
- `styles.py` / `generate.py`：参考三种话术、每种两条的候选结构；在 `replies.py` 中重写飞书场景提示词与本机 Ollama 调用。
- `hud.py`：参考 `NSPanel` 非激活悬浮窗及菜单栏启动方式；`hud.py` 为本项目独立界面，不包含微信感知或填入操作。
- 未复用上游内置通道或微信专用感知/填入逻辑。
- 不安装 torch、transformers、laya 或 huggingface-hub；不从已安装 App 导入模块。

后续如复用具体实现，应在此逐项追加来源文件和修改边界。
