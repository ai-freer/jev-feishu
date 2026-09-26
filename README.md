# Jev 飞书 Mac 伴随助手

独立的本机飞书伴随应用：识别前台聊天，经 `lark-cli` 只读最近一页消息，用本机 Ollama 生成六条可编辑、可复制的候选回复。TypeSafe Jev 判断全局默认开启，可在设置中关闭。应用没有填入或发送功能。

**当前状态：开发原型，尚未完成正式首版验收。** 全局安装包的辅助功能授权、指定单聊识别、暂停恢复、虚构候选编辑/复制及设置连接测试已通过；普通群聊、单聊↔群聊切换和真实编辑/撤回等仍待实测。

## 运行条件

- macOS arm64；本项目开发环境使用 Python 3.12、`uv` 和 PyObjC。构建机需有 Rust `rustc`/`rust-lld` 与 macOS SDK。
- 飞书 Mac 客户端已登录；安装公开的 [`@larksuite/cli`](https://github.com/larksuite/cli)（官方安装命令：`npx @larksuite/cli@latest install`），完成用户身份配置与授权，确保本机可找到 `lark-cli`。开发验收使用 1.0.95；可通过 `lark-cli auth status --json --verify` 检查授权。
- 本机 Ollama 监听 `127.0.0.1:11434`，已安装 `qwen3.5:4b`；可选 `qwen3.5:9b`。
- 云端 Jev 需要在 `~/.config/typesafe/env` 中设置 `TYPESAFE_API_KEY`，该文件须为 0600 权限；不要将密钥提交到仓库。未配置时应用仍可生成本机候选，但 Jev 会显示“未配置”。
- 自动识别需要为 **`/Applications/Jev 飞书助手.app`** 授予 macOS 的 AX 窗口访问权限。在当前 macOS 27 中，路径是「系统设置 → 隐私与安全性 → 设备控制与数据访问」；较早的 macOS 版本通常列在「辅助功能」。这是读取飞书控件结构的权限，不是“屏幕录制”。只对 `/Applications` 中的安装包授权，不对 `dist/` 构建副本授权。

在本项目目录构建：

```bash
packaging/build_app.sh
bash packaging/install_app.sh
open "/Applications/Jev 飞书助手.app"
```

构建脚本在系统临时目录生成并签名独立应用，内置 Python 运行时，再发布到项目 `dist/` 并对发布产物的干净副本做严格签名复核；临时目录自动清理。当本机恰有一个 Apple Development 签名身份时自动使用，以保持应用的系统权限身份稳定。没有可用身份时退回临时本机签名；有多个身份时须设置 `JEV_FEISHU_SIGN_IDENTITY` 指定证书。

当前项目位于受 macOS 文件提供者管理的 `Documents` 目录，系统可能给发布后的包重新附加 Finder 信息，使原位置的直接签名复核失败；安装脚本会复制到 `/Applications`、清理属性并再次严格验证。只使用 `/Applications/Jev 飞书助手.app` 进行日常运行和验收。

源码调试可用 `PYTHONPATH=src uv run --no-sync python -m jev_feishu.app`。应用默认暂停；打开飞书测试聊天后点「开始跟随」。只有当前窗口结构与 API 身份唯一匹配时才读消息。识别失败会停读并清空旧候选。菜单栏「Jev → 手动指定会话…」可用于主动联调，输入已确认的 `oc_…` 会话 ID 或 `ou_…` 用户 ID；它不是自动识别的替代验收。

启动器禁止向包内写入 Python 字节码缓存，以保持运行后的签名完整性；直接调用包内 Python 做开发检查时也需传入 `-B`。

从 Finder 启动时，应用会为飞书 CLI 的子进程补充其安装目录，使 NVM/Homebrew 安装的同目录 Node 可用；不会修改系统或终端的 PATH。

候选由 4B 或 9B 在本机生成；点击文本框可编辑，点击「复制」后仍需自行检查并在飞书发送。Jev 全局默认开启：开始跟随后，已可靠识别的普通文本聊天会将最新文本及最多前两条文本上下文经 OpenRouter 发送至 TypeSafe。设置页可全局关闭 Jev，不影响本机候选；关闭状态会保存并在重启后生效。未识别、暂停或最新消息为本人发送时不触发 Jev。

切换 4B/9B 或改变全局 Jev 开关会清空旧结果并重新读取当前消息。模型失败后可点击候选区「重试」，重新处理当前消息。

关闭悬浮窗会暂停跟随，菜单栏应用继续运行。可通过「Jev → 显示悬浮窗」或在 Finder 中再次打开 `/Applications/Jev 飞书助手.app` 恢复窗口；恢复窗口不会自动开始读取。

配置文件是 `~/.config/jev-feishu/env`，首次启动以 0600 权限创建，默认 `JEV_FEISHU_REPLY_MODEL=qwen3.5:4b` 和 `JEV_FEISHU_JEV_ENABLED=true`；已有文件缺少新键时也默认为开启。TypeSafe 配置从现有 `~/.config/typesafe/env` 只读取得，不复制密钥；飞书令牌由 `lark-cli` 管理。详见[隐私说明](PRIVACY.md)。

## 设置与排错

点击悬浮窗底部「设置…」或菜单栏「Jev → 设置与连接检查…」。页面提供“Jev 云端判断（全局）”开关，显示本次启动实际使用的模型、服务地址及依赖状态，密钥仅显示是否已配置。打开设置页会暂停跟随；全局开关保存失败时保持原值并显示错误。启动时在后台检查飞书 CLI、用户授权和 Ollama 模型清单；不会自动发送模型测试文本。飞书认证不可用时仍保留窗口，禁用开始跟随，重新授权后可点击「重新检查依赖」。

「测试本机候选」和「测试 Jev」只使用固定虚构问候，不读取当前聊天、不改变全局 Jev 设置。结果仅显示状态、候选数量与耗时。模型可能返回不足两条回复，界面会显示“候选数量不足”；可在此重试连接测试。关闭设置页后需点击「开始跟随」。手动修改配置文件后重新启动应用，以使用新的有效配置。

读取错误会清空已有候选；当前消息为本人发送、已撤回或没有可处理普通文本时显示对应状态。界面失去飞书当前聊天身份时停止读取，不以旧候选代替新会话结果。

## 开发验证

```bash
PYTHONPATH=src uv run --no-sync python -m unittest discover -s tests -v
PYTHONPATH=src uv run --no-sync python -m compileall -q src
codesign --verify --deep --strict "/Applications/Jev 飞书助手.app"
```

测试使用虚构消息和模拟 CLI/HTTP 响应；完整测试不会读取真实聊天。以上命令在仓库根目录运行。上游来源见[来源说明](docs/upstream.md)。

构建并安装后，还可检查实际安装模块的虚构完整链路：

```bash
"/Applications/Jev 飞书助手.app/Contents/MacOS/JevFeishuPython" -B tests/manual_hud_fixture.py --check
```

去掉 `--check` 可打开标有「虚构验收」的原生悬浮窗及测试控制台，模拟单聊/群聊切换、编辑、撤回、模型故障和授权失效。该脚本仅替换外部 CLI/HTTP 与前台观察输入，运行安装包中的正式模块，不读取真实聊天、配置密钥或调用网络。`--check` 只证明包内模块链路，不能代替真实前台识别、原生交互或正式验收。

用同一包内 Python 执行 `-B tests/measure_installed_replies.py`，可用固定虚构消息分别测量 4B/9B 两次完整六候选生成；它调用真实本机 Ollama，只输出耗时、数量、错误类别及请求前后的模型驻留状态。不会主动卸载共享模型，首轮是否包含加载以实际驻留状态为准。
