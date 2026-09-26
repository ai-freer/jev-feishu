"""Native floating panel for review, editing and explicit copying."""

import AppKit
from Foundation import NSObject, NSMakeRect, NSTimer
import objc


WIDTH, HEIGHT = 480, 590
STATUS_TEXT = {
    "paused": "已暂停",
    "checking_dependencies": "正在检查飞书授权与本机模型…",
    "lark_auth_unavailable": "飞书授权不可用；请打开设置与连接检查",
    "looking_for_chat": "正在确认当前聊天…",
    "unidentified": "无法可靠识别当前聊天，已停读",
    "accessibility_required": "需要为本应用开启 macOS 辅助功能权限；已停读",
    "lookup_error": "会话身份查询失败，已停读",
    "read_error": "消息读取失败；请在设置中检查飞书授权",
    "no_text": "暂无可处理的普通文本消息",
    "message_deleted": "最新消息已撤回，已清空候选",
    "own_message": "最新消息由本人发送，等待对方消息",
    "generating": "正在生成本机候选…",
    "refreshing": "正在重新读取当前消息…",
    "ready": "就绪",
    "manual": "手动模式：仅读取指定会话",
    "not_configured": "Jev 未配置；本机候选仍可用",
    "unauthorized": "Jev 授权失效；本机候选仍可用",
    "rate_limited": "Jev 请求受限；本机候选仍可用",
    "connection_error": "模型连接失败",
    "http_error": "模型服务返回错误；请在设置中测试连接",
    "invalid_response": "模型响应格式无效，请重新生成",
    "thinking_only": "模型只返回思考内容",
    "insufficient_candidates": "候选数量不足",
    "internal_error": "处理失败",
}


class HUDController(NSObject):
    def initWithRuntime_(self, runtime):
        self = objc.super(HUDController, self).init()
        if self is None:
            return None
        self.runtime = runtime
        self._rendered_result = None
        self.settings_panel = None
        self._build()
        return self

    @objc.python_method
    def _label(self, frame, text, size=13):
        field = AppKit.NSTextField.alloc().initWithFrame_(frame)
        field.setStringValue_(text)
        field.setEditable_(False)
        field.setBezeled_(False)
        field.setDrawsBackground_(False)
        field.setFont_(AppKit.NSFont.systemFontOfSize_(size))
        return field

    @objc.python_method
    def _button(self, frame, title, action, tag=None):
        button = AppKit.NSButton.alloc().initWithFrame_(frame)
        button.setTitle_(title)
        button.setTarget_(self)
        button.setAction_(action)
        if tag is not None:
            button.setTag_(tag)
        return button

    @objc.python_method
    def _build(self):
        style = (AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable
                 | AppKit.NSWindowStyleMaskNonactivatingPanel)
        self.panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, HEIGHT), style, AppKit.NSBackingStoreBuffered, False)
        self.panel.setTitle_("Jev 飞书助手")
        self.panel.setReleasedWhenClosed_(False)
        self.panel.setLevel_(AppKit.NSFloatingWindowLevel)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setBecomesKeyOnlyIfNeeded_(True)
        self.panel.setDelegate_(self)
        self.panel.center()
        view = self.panel.contentView()

        self.status = self._label(NSMakeRect(18, 550, 440, 24), "已暂停", 14)
        view.addSubview_(self.status)
        self.chat = self._label(NSMakeRect(18, 520, 440, 24), "当前会话：未识别")
        view.addSubview_(self.chat)
        self.run_button = self._button(NSMakeRect(18, 482, 110, 30), "开始跟随", "toggleRun:")
        view.addSubview_(self.run_button)
        self.model_select = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(286, 482, 175, 30), False)
        self.model_select.addItemsWithTitles_(["qwen3.5:4b", "qwen3.5:9b"])
        self.model_select.setTarget_(self)
        self.model_select.setAction_("modelChanged:")
        view.addSubview_(self.model_select)

        self.verdict = self._label(NSMakeRect(18, 449, 440, 22), "Jev：本会话未开启")
        view.addSubview_(self.verdict)
        view.addSubview_(self._label(NSMakeRect(18, 420, 360, 22), "候选回复（编辑、复制后自行发送）", 13))
        self.retry_button = self._button(NSMakeRect(389, 415, 72, 29), "重试", "retryCurrent:")
        self.retry_button.setEnabled_(False)
        view.addSubview_(self.retry_button)
        self.fields = []
        for index in range(6):
            y = 366 - index * 58
            field = AppKit.NSTextField.alloc().initWithFrame_(NSMakeRect(18, y, 362, 45))
            field.setEditable_(True)
            field.setBezeled_(True)
            field.setStringValue_("")
            field.setDelegate_(self)
            view.addSubview_(field)
            self.fields.append(field)
            button = self._button(NSMakeRect(389, y + 7, 72, 29), "复制", "copyReply:", index)
            view.addSubview_(button)
        self.permission = self._label(NSMakeRect(18, 38, 350, 22), "辅助功能：检查中", 11)
        view.addSubview_(self.permission)
        view.addSubview_(self._button(NSMakeRect(389, 36, 72, 26), "设置…", "showSettings:"))
        self.hint = self._label(NSMakeRect(18, 13, 440, 22), "仅在已确认的飞书聊天中读取；不会自动发送。", 11)
        view.addSubview_(self.hint)

        bar = AppKit.NSStatusBar.systemStatusBar()
        self.status_item = bar.statusItemWithLength_(AppKit.NSVariableStatusItemLength)
        self.status_item.button().setTitle_("Jev")
        menu = AppKit.NSMenu.alloc().init()
        for title, action in (("显示悬浮窗", "showPanel:"),
                              ("设置与连接检查…", "showSettings:"),
                              ("开始 / 暂停跟随", "toggleRun:"),
                              ("手动指定会话…", "chooseManual:"),
                              ("退出手动模式", "exitManual:"),
                              ("退出", "quitApp:")):
            menu.addItemWithTitle_action_keyEquivalent_(title, action, "")
        for item in menu.itemArray():
            item.setTarget_(self)
        self.status_item.setMenu_(menu)
        self.panel.orderFrontRegardless()

    def tick_(self, _timer):
        settings_focused = bool(self.settings_panel and self.settings_panel.isKeyWindow())
        if self.runtime._overlay_focused and not self.panel.isKeyWindow() and not settings_focused:
            self.runtime.set_overlay_focused(False)
        self.runtime.pulse()
        self._render(self.runtime.display())
        if self.settings_panel:
            self.settings_info.setStringValue_(self.runtime.settings_text())
            for button in self.settings_buttons:
                button.setEnabled_(not self.runtime.diagnostics_busy)

    @objc.python_method
    def _render(self, state):
        import ApplicationServices as AX

        status = STATUS_TEXT.get(state.status, "处理中")
        if self.runtime._manual and state.status != "manual":
            status = "手动模式 · " + status
        self.status.setStringValue_(status)
        self.chat.setStringValue_("当前会话：" + (state.chat_title or "未识别"))
        self.run_button.setTitle_("暂停跟随" if self.runtime._running else "开始跟随")
        self.run_button.setEnabled_(self.runtime.can_start)
        self.retry_button.setEnabled_(bool(state.chat_title) and state.status not in ("generating", "refreshing"))
        self.model_select.selectItemWithTitle_(state.model)
        self.permission.setStringValue_("辅助功能：已授权" if AX.AXIsProcessTrusted()
                                        else "辅助功能：未授权，请在系统设置中添加本应用")
        if state.result is not self._rendered_result:
            self._rendered_result = state.result
            replies = state.result.replies if state.result else ()
            for index, field in enumerate(self.fields):
                field.setStringValue_(replies[index] if index < len(replies) else "")
        if state.result and state.result.verdict:
            verdict = state.result.verdict
            self.verdict.setStringValue_(f"Jev：{verdict.intent} · 风险 {verdict.risk:.1f}/9")
        else:
            self.verdict.setStringValue_("Jev：" + ("等待判断" if state.cloud_enabled else "全局关闭"))

    def toggleRun_(self, _sender):
        if self.runtime._manual:
            self.runtime.exit_manual()
        elif self.runtime._running:
            self.runtime.pause()
        else:
            import ApplicationServices as AX

            if AX.AXIsProcessTrusted():
                self.runtime.start()
            else:
                AX.AXIsProcessTrustedWithOptions({AX.kAXTrustedCheckOptionPrompt: True})
        self._render(self.runtime.display())

    def modelChanged_(self, sender):
        self.runtime.set_model(str(sender.titleOfSelectedItem()))

    def retryCurrent_(self, _sender):
        self.runtime.retry_current()
        self._render(self.runtime.display())

    def chooseManual_(self, _sender):
        from .chat_picker import choose_manual_ref
        ref = choose_manual_ref()
        if ref is not None:
            self.runtime.enter_manual(ref)
            self._render(self.runtime.display())

    def exitManual_(self, _sender):
        if self.runtime._manual:
            self.runtime.exit_manual()
            self._render(self.runtime.display())

    def copyReply_(self, sender):
        index = sender.tag()
        value = self.fields[index].stringValue().strip()
        if not value:
            return
        pasteboard = AppKit.NSPasteboard.generalPasteboard()
        pasteboard.clearContents()
        pasteboard.setString_forType_(value, AppKit.NSPasteboardTypeString)
        self.hint.setStringValue_("已复制候选；请在飞书中自行检查并发送。")

    def showPanel_(self, _sender):
        self.panel.orderFrontRegardless()

    def applicationShouldHandleReopen_hasVisibleWindows_(self, _app, _visible):
        self.panel.orderFrontRegardless()
        return False

    def showSettings_(self, _sender):
        self.runtime.pause()
        self._render(self.runtime.display())
        if self.settings_panel is None:
            style = AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable
            self.settings_panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 640, 400), style, AppKit.NSBackingStoreBuffered, False)
            self.settings_panel.setTitle_("Jev 设置与连接检查")
            self.settings_panel.setReleasedWhenClosed_(False)
            self.settings_panel.setDelegate_(self)
            self.settings_panel.center()
            view = self.settings_panel.contentView()
            self.settings_info = self._label(NSMakeRect(20, 115, 600, 220), "", 13)
            self.settings_info.setSelectable_(True)
            view.addSubview_(self.settings_info)
            self.jev_switch = self._button(NSMakeRect(20, 348, 400, 27),
                                           "Jev 云端判断（全局）", "toggleJev:")
            self.jev_switch.setButtonType_(AppKit.NSSwitchButton)
            view.addSubview_(self.jev_switch)
            self.settings_buttons = []
            for x, title, action in ((20, "重新检查依赖", "refreshDependencies:"),
                                     (218, "测试本机候选", "testLocal:"),
                                     (416, "测试 Jev", "testJev:")):
                button = self._button(NSMakeRect(x, 55, 190, 32), title, action)
                view.addSubview_(button)
                self.settings_buttons.append(button)
            view.addSubview_(self._label(NSMakeRect(20, 14, 600, 30),
                "连接测试只发送虚构问候；关闭此窗口后可手动开始跟随。", 12))
        self.settings_info.setStringValue_(self.runtime.settings_text())
        self.jev_switch.setState_(AppKit.NSControlStateValueOn if self.runtime.jev_enabled
                                  else AppKit.NSControlStateValueOff)
        self.settings_panel.makeKeyAndOrderFront_(None)
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    def toggleJev_(self, sender):
        enabled = sender.state() == AppKit.NSControlStateValueOn
        if not self.runtime.set_jev_enabled(enabled):
            sender.setState_(AppKit.NSControlStateValueOn if self.runtime.jev_enabled
                             else AppKit.NSControlStateValueOff)
        self.settings_info.setStringValue_(self.runtime.settings_text())
        self._render(self.runtime.display())

    def refreshDependencies_(self, _sender):
        self.runtime.refresh_dependencies()

    def testLocal_(self, _sender):
        self.runtime.test_connection("ollama")

    def testJev_(self, _sender):
        self.runtime.test_connection("jev")

    def controlTextDidBeginEditing_(self, _notification):
        self.runtime.set_overlay_focused(True)

    def controlTextDidEndEditing_(self, _notification):
        if not self.panel.isKeyWindow():
            self.runtime.set_overlay_focused(False)

    def windowDidBecomeKey_(self, _notification):
        self.runtime.set_overlay_focused(True)

    def windowDidResignKey_(self, _notification):
        self.runtime.set_overlay_focused(False)

    def windowWillClose_(self, _notification):
        self.runtime.pause()

    def quitApp_(self, _sender):
        self.runtime.close()
        AppKit.NSApplication.sharedApplication().terminate_(None)
