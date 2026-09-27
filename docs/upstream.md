# 上游来源与复用边界

- 来源：https://github.com/jev-chat/jev-chat-jarvis-mac
- 固定标签：`v0.5.0`
- 固定提交：`5814df87cf2a6f6b3210208d8afdb62ce6f5f386`
- 核验日期：2026-09-24；独立临时克隆的 HEAD 与计划一致。
- `LICENSE`：本项目以 MIT 发布，新增实现署名为 ai-freer；因下述文案沿用，保留上游 MIT 授权文本及 eatmoreduck 原版权声明。构建的 `.app` 也包含此文件。
- `pyproject.toml`：仅选择上游的 ApplicationServices 和 Cocoa 依赖及最低版本，供后续 AX 与悬浮窗使用。
- `judge_jev.py` / `judge.py`：`jev.py` 逐字沿用上游八项意图说明、十级风险文案与两条 Jev 问题提示；请求传输、响应校验和全局开关逻辑在本项目中重新实现。
- `styles.py` / `generate.py`：参考三个展示位、每种两条的候选结构；在 `replies.py` 中为飞书重写九种工作回复模式、公共系统规则和本机 Ollama 调用。两条候选分别为“简短回应”和“推进一步”，不沿用上游的第二条夸张化要求。
- `hud.py`：参考 `NSPanel` 非激活悬浮窗及菜单栏启动方式；`hud.py` 为本项目独立界面，不包含微信感知或填入操作。
- 未复用上游内置通道或微信专用感知/填入逻辑。
- 不安装 torch、transformers、laya 或 huggingface-hub；不从已安装 App 导入模块。

后续如复用具体实现，应在此逐项追加来源文件和修改边界。

## 可编辑模型设置参考

本次对照上游最新正式发布 `v0.6.0`，并阅读 `master` 固定提交 `01312b05655566a4ba4479899373a6826e95867d` 的 `src/settings.py`、`src/settings_config.py`、`src/generate.py` 与 `src/userconfig.py`。参考其地址/模型/密钥编辑、显式模型列表与虚构连接测试、配置冲突检查及“保存后重启生效”的交互，在本项目的 `model_settings.py`、`model_services.py`、`config.py`、`hud.py` 中适配实现。

飞书版默认仍走本机回复，远端由用户显式选择；只读继承共享 TypeSafe 配置，覆盖项写入本应用 0600 配置。未复制上游内置代理或共享密钥，也未引入微信感知、填入、离线判断模型下载或聊天历史功能。
