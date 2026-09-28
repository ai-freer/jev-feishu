"""Native floating panel for review, editing and explicit copying."""

import AppKit
from Foundation import NSObject, NSMakeRect, NSTimer
import objc
from . import __version__

from .replies import TONES
from .model_services import PROVIDERS, PROVIDER_BASES, is_loopback
from .model_settings import ModelSettingsEditor, settings_error


WIDTH, HEIGHT = 500, 670
REPLY_HINT = "AI 草稿：请核对事实与承诺，复制后自行发送。"
ACTION_HINTS = {
    "派活": "先确认交付范围和期限",
    "催进度": "报当前状态，再给下一节点",
    "问进度": "报已完成部分和下次更新时间",
    "批评": "确认问题，说明补救动作",
    "要解释": "先讲事实，再说明改进",
    "闲聊": "简短回应，延续话题",
    "约会议": "确认时间和讨论议题",
    "夸奖": "表示感谢，回应具体成果",
}
STATUS_TEXT = {
    "viewport_unmatched": "可见消息无法唯一定位；请稍微滚动或切换跟随最新",
    "viewport_settling": "等待滚动停稳…",
    "paused": "已暂停",
    "checking_dependencies": "正在检查飞书授权与本机模型…",
    "lark_auth_unavailable": "飞书授权不可用；请打开设置与连接检查",
    "lark_check_failed": "飞书授权校验未完成或失败；请重新检查",
    "lark_cli_missing": "未找到飞书 CLI；请在设置中检查安装",
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
    "not_configured": "模型密钥未配置；请在设置中检查",
    "unauthorized": "模型认证失败；请在设置中检查",
    "rate_limited": "模型请求受限；请稍后重试",
    "connection_error": "模型连接失败",
    "http_error": "模型服务返回错误；请在设置中测试连接",
    "invalid_response": "模型响应格式无效，请重新生成",
    "thinking_only": "模型只返回思考内容",
    "insufficient_candidates": "候选数量不足",
    "internal_error": "处理失败",
}


def message_preview(text: str, limit: int = 60) -> str:
    value = " ".join(text.split())
    return value[:limit] + "…" if len(value) > limit else value


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
    def _label(self, frame, text, size=13, *, bold=False, secondary=False):
        field = AppKit.NSTextField.alloc().initWithFrame_(frame)
        field.setStringValue_(text)
        field.setEditable_(False)
        field.setBezeled_(False)
        field.setDrawsBackground_(False)
        field.setFont_(AppKit.NSFont.boldSystemFontOfSize_(size) if bold
                       else AppKit.NSFont.systemFontOfSize_(size))
        field.cell().setLineBreakMode_(AppKit.NSLineBreakByTruncatingTail)
        if secondary:
            field.setTextColor_(AppKit.NSColor.secondaryLabelColor())
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
    def _reply_editor(self, frame):
        scroll = AppKit.NSScrollView.alloc().initWithFrame_(frame)
        scroll.setBorderType_(AppKit.NSBezelBorder)
        scroll.setHasVerticalScroller_(True)
        scroll.setHasHorizontalScroller_(False)
        scroll.setAutohidesScrollers_(True)
        size = scroll.contentSize()
        field = AppKit.NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, size.width, size.height))
        field.setMinSize_((0, size.height))
        field.setMaxSize_((size.width, 1e7))
        field.setVerticallyResizable_(True)
        field.setHorizontallyResizable_(False)
        field.setAutoresizingMask_(AppKit.NSViewWidthSizable)
        field.textContainer().setContainerSize_((size.width, 1e7))
        field.textContainer().setWidthTracksTextView_(True)
        field.setTextContainerInset_((4, 3))
        field.setRichText_(False)
        field.setImportsGraphics_(False)
        field.setAllowsUndo_(True)
        field.setFont_(AppKit.NSFont.systemFontOfSize_(13))
        field.setDelegate_(self)
        scroll.setDocumentView_(field)
        return scroll, field

    @objc.python_method
    def _build(self):
        style = (AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable
                 | AppKit.NSWindowStyleMaskNonactivatingPanel)
        self.panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, HEIGHT), style, AppKit.NSBackingStoreBuffered, False)
        self.panel.setTitle_(f"Jev 飞书助手 {__version__}")
        self.panel.setReleasedWhenClosed_(False)
        self.panel.setLevel_(AppKit.NSFloatingWindowLevel)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setBecomesKeyOnlyIfNeeded_(True)
        self.panel.setDelegate_(self)
        self.panel.center()
        view = self.panel.contentView()

        self.status = self._label(NSMakeRect(20, 638, 460, 20), "已暂停", 12, secondary=True)
        view.addSubview_(self.status)
        self.chat = self._label(NSMakeRect(20, 604, 460, 27), "当前会话：未识别", 17, bold=True)
        view.addSubview_(self.chat)
        self.run_button = self._button(NSMakeRect(20, 562, 120, 32), "开始跟随", "toggleRun:")
        view.addSubview_(self.run_button)
        self.follow_select = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(143, 562, 155, 32), False)
        self.follow_select.addItemsWithTitles_(["跟随最新消息", "跟随可见消息"])
        self.follow_select.setTarget_(self)
        self.follow_select.setAction_("followModeChanged:")
        self.follow_select.setToolTip_("可见模式：滚动停稳后回应最下方完整可见的对方纯文字消息；无法可靠定位时停读。")
        view.addSubview_(self.follow_select)
        self.model_select = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
            NSMakeRect(302, 562, 178, 32), False)
        self.model_select.addItemsWithTitles_(list(self.runtime.available_reply_models))
        self.model_select.setTarget_(self)
        self.model_select.setAction_("modelChanged:")
        view.addSubview_(self.model_select)

        view.addSubview_(self._label(NSMakeRect(20, 534, 460, 17), "当前消息", 11, secondary=True))
        self.source = self._label(NSMakeRect(20, 489, 460, 40), "等待当前消息", 14)
        self.source.cell().setUsesSingleLineMode_(False)
        self.source.cell().setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
        view.addSubview_(self.source)
        self.verdict = self._label(NSMakeRect(20, 458, 460, 25), "Jev：等待判断", 14, bold=True)
        view.addSubview_(self.verdict)
        self.advice = self._label(NSMakeRect(20, 434, 460, 20), "", 12, secondary=True)
        view.addSubview_(self.advice)
        view.addSubview_(self._label(NSMakeRect(20, 400, 370, 25),
                                    "回复 · 简短回应 / 推进一步", 13, bold=True))
        self.retry_button = self._button(NSMakeRect(406, 397, 74, 29), "重试", "retryCurrent:")
        self.retry_button.setEnabled_(False)
        view.addSubview_(self.retry_button)
        self.fields = []
        self.tone_selectors = []
        for tone_index, tone in enumerate(self.runtime.display().tones):
            heading_y = 368 - tone_index * 108
            selector = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(20, heading_y, 370, 22), False)
            selector.addItemsWithTitles_(list(TONES))
            for name, instruction in TONES.items():
                selector.itemWithTitle_(name).setToolTip_(instruction)
            selector.selectItemWithTitle_(tone)
            selector.setAccessibilityLabel_(f"第{tone_index + 1}组回复模式")
            selector.setTarget_(self)
            selector.setAction_("toneChanged:")
            selector.setTag_(tone_index)
            view.addSubview_(selector)
            self.tone_selectors.append(selector)
            for offset in range(2):
                index = tone_index * 2 + offset
                y = heading_y - 40 - offset * 44
                scroll, field = self._reply_editor(NSMakeRect(20, y, 370, 38))
                field.setAccessibilityLabel_(f"第{tone_index + 1}组" + ("简短回应" if offset == 0 else "推进一步"))
                field.setToolTip_("可编辑；长回复可在框内滚动查看，复制会保留全文。")
                view.addSubview_(scroll)
                self.fields.append(field)
                view.addSubview_(self._button(NSMakeRect(406, y + 4, 74, 30),
                                              "复制", "copyReply:", index))
        self.permission = self._label(NSMakeRect(20, 39, 370, 20), "辅助功能：检查中", 11,
                                      secondary=True)
        view.addSubview_(self.permission)
        view.addSubview_(self._button(NSMakeRect(406, 35, 74, 28), "设置…", "showSettings:"))
        self.hint = self._label(NSMakeRect(20, 12, 460, 20), REPLY_HINT, 11, secondary=True)
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
            self._poll_model_task()
            busy = self._settings_future is not None
            for control in self.settings_controls:
                control.setEnabled_(not busy)

    @objc.python_method
    def _render(self, state):
        import ApplicationServices as AX

        status = STATUS_TEXT.get(state.status, "处理中")
        if state.result and state.status in ("not_configured", "unauthorized", "rate_limited"):
            label = {"not_configured": "未配置密钥", "unauthorized": "认证失败", "rate_limited": "请求受限"}[state.status]
            status = ("Jev " + label + "；回复候选仍可用" if state.result.replies else "回复服务" + label)
        if state.status == "generating" and self.runtime.reply_provider != "ollama":
            status = "正在生成回复候选…"
        if self.runtime._manual and state.status != "manual":
            status = "手动模式 · " + status
        self.status.setStringValue_(status)
        self.status.setTextColor_(AppKit.NSColor.systemGreenColor()
                                  if state.status in ("ready", "manual") else
                                  AppKit.NSColor.secondaryLabelColor())
        self.chat.setStringValue_("当前会话：" + (state.chat_title or "未识别"))
        self.run_button.setTitle_("暂停跟随" if self.runtime._running else
                                  "检查中…" if state.status == "checking_dependencies" else
                                  "开始跟随" if self.runtime.can_start else "重新检查")
        self.run_button.setEnabled_(self.runtime.can_start or self.runtime.can_recheck)
        self.retry_button.setEnabled_(bool(state.chat_title) and state.status not in ("generating", "refreshing"))
        models = list(self.runtime.available_reply_models)
        if list(self.model_select.itemTitles()) != models:
            self.model_select.removeAllItems()
            self.model_select.addItemsWithTitles_(models)
        self.model_select.selectItemWithTitle_(state.model)
        self.permission.setStringValue_("辅助功能：已授权" if AX.AXIsProcessTrusted()
                                        else "辅助功能：未授权，请在系统设置中添加本应用")
        self.source.setStringValue_(message_preview(state.result.source_text)
                                    if state.result and state.result.source_text else "等待当前消息")
        self.source.setToolTip_(state.result.source_text if state.result and state.result.source_text else None)
        for index, selector in enumerate(self.tone_selectors):
            selector.selectItemWithTitle_(state.tones[index])
            selector.setToolTip_(TONES[state.tones[index]])
        if state.result is not self._rendered_result:
            self._rendered_result = state.result
            self.hint.setStringValue_(REPLY_HINT)
            replies = state.result.replies if state.result else ()
            for index, field in enumerate(self.fields):
                undo = field.undoManager()
                if undo is not None:
                    undo.removeAllActions()
                field.setString_(replies[index] if index < len(replies) else "")
                field.scrollRangeToVisible_((0, 0))
        if state.result and state.result.verdict:
            verdict = state.result.verdict
            self.verdict.setStringValue_(
                f"Jev：{verdict.intent}（{verdict.confidence:.0%}）  风险 {verdict.risk:.1f}/9")
            self.verdict.setTextColor_(AppKit.NSColor.systemGreenColor() if verdict.risk < 3
                                       else AppKit.NSColor.systemOrangeColor() if verdict.risk < 7
                                       else AppKit.NSColor.systemRedColor())
            self.advice.setStringValue_("回应要点：" + ACTION_HINTS.get(verdict.intent, "先确认对方诉求"))
        else:
            self.verdict.setStringValue_("Jev：" + ("等待判断" if state.cloud_enabled else "全局关闭"))
            self.verdict.setTextColor_(AppKit.NSColor.labelColor())
            self.advice.setStringValue_("")

    def toggleRun_(self, _sender):
        if self.runtime._manual:
            self.runtime.exit_manual()
        elif self.runtime._running:
            self.runtime.pause()
        elif not self.runtime.can_start:
            if self.runtime.can_recheck:
                self.runtime.refresh_dependencies()
        else:
            import ApplicationServices as AX

            if AX.AXIsProcessTrusted():
                self.runtime.start()
            else:
                AX.AXIsProcessTrustedWithOptions({AX.kAXTrustedCheckOptionPrompt: True})
        self._render(self.runtime.display())

    def modelChanged_(self, sender):
        self.runtime.set_model(str(sender.titleOfSelectedItem()))

    def followModeChanged_(self, sender):
        self.runtime.set_follow_mode("visible" if sender.indexOfSelectedItem() == 1 else "latest")
        self._render(self.runtime.display())

    def toneChanged_(self, sender):
        index = sender.tag()
        saved = self.runtime.set_tone(index, str(sender.titleOfSelectedItem()))
        if not saved:
            sender.selectItemWithTitle_(self.runtime.display().tones[index])
        self._render(self.runtime.display())
        if not saved:
            self.hint.setStringValue_("回复模式保存失败；选择未改变。")

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
        value = self.fields[index].string().strip()
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
        if self.settings_panel is not None and self.settings_panel.isVisible():
            self.settings_panel.makeKeyAndOrderFront_(None)
            return
        self._settings_future = None
        try:
            self._model_editor = ModelSettingsEditor()
        except (OSError, ValueError):
            self.hint.setStringValue_("模型配置无法读取，请检查配置文件格式与权限。")
            return
        if self.settings_panel is None:
            style = AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskClosable
            self.settings_panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(0, 0, 720, 780), style, AppKit.NSBackingStoreBuffered, False)
            self.settings_panel.setTitle_("Jev 模型设置 · 保存后重启生效")
            self.settings_panel.setReleasedWhenClosed_(False)
            self.settings_panel.setDelegate_(self)
            self.settings_panel.center()
            view = self.settings_panel.contentView()
            view.addSubview_(self._label(NSMakeRect(20, 735, 460, 30), "模型设置", 20, bold=True))
            self.jev_switch = self._button(NSMakeRect(20, 700, 660, 27),
                                           "Jev 云端判断（全局，即时生效）", "toggleJev:")
            self.jev_switch.setButtonType_(AppKit.NSSwitchButton)
            view.addSubview_(self.jev_switch)
            self.settings_controls = [self.jev_switch]
            self.model_fields = {}
            self.model_clear = {}
            self.model_key_notes = {}
            for target, title, y in (("jev", "判断 · Jev / System One", 663),
                                      ("reply", "候选回复", 518)):
                view.addSubview_(self._label(NSMakeRect(20, y, 310, 24), title, 14, bold=True))
                for index, (name, caption) in enumerate((("base", "服务地址"), ("model", "模型 ID"), ("key", "API 密钥"))):
                    row_y = y - 34 - index * 35
                    view.addSubview_(self._label(NSMakeRect(20, row_y, 96, 24), caption, 12))
                    cls = AppKit.NSSecureTextField if name == "key" else AppKit.NSComboBox if name == "model" else AppKit.NSTextField
                    width = 560 if name == "base" else 355 if name == "model" else 420
                    field = cls.alloc().initWithFrame_(NSMakeRect(126, row_y, width, 25))
                    field.setFont_(AppKit.NSFont.systemFontOfSize_(12))
                    field.setEditable_(True)
                    field.setAccessibilityLabel_(title + " " + caption)
                    if name == "model":
                        field.setUsesDataSource_(False)
                        field.setCompletes_(True)
                        field.setPlaceholderString_("从列表选择或手动填写模型 ID")
                    elif name == "key":
                        field.setPlaceholderString_("留空保留已有密钥；输入新值才替换")
                    view.addSubview_(field)
                    self.model_fields[(target, name)] = field
                    self.settings_controls.append(field)
                for x, caption, action in ((490, "获取列表", "listModels:"), (594, "测试连接", "testDraft:")):
                    button = self._button(NSMakeRect(x, y - 69, 94, 25), caption, action,
                                          0 if target == "jev" else 1)
                    view.addSubview_(button)
                    self.settings_controls.append(button)
                clear = self._button(NSMakeRect(560, y - 104, 130, 25), "清除密钥", "settingsFieldChanged:")
                clear.setButtonType_(AppKit.NSSwitchButton)
                self.model_clear[target] = clear
                self.settings_controls.append(clear)
                view.addSubview_(clear)
                note = self._label(NSMakeRect(126, y - 123, 560, 17), "", 10, secondary=True)
                self.model_key_notes[target] = note
                view.addSubview_(note)
            self.reply_protocol = AppKit.NSPopUpButton.alloc().initWithFrame_pullsDown_(
                NSMakeRect(340, 518, 346, 27), False)
            self.reply_protocol.addItemsWithTitles_(list(PROVIDERS.values()))
            self.reply_protocol.setTarget_(self)
            self.reply_protocol.setAction_("replyProtocolChanged:")
            view.addSubview_(self.reply_protocol)
            self.settings_controls.append(self.reply_protocol)
            warning = self._label(NSMakeRect(20, 339, 670, 52),
                "默认本机生成。选用远端回复服务后，开始跟随会将当前文本及上下文发往所填地址。"
                "Jev 开关只控制判断，不控制远端回复。更换服务请提供新密钥或明确清除。", 11, secondary=True)
            warning.cell().setUsesSingleLineMode_(False)
            warning.cell().setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
            view.addSubview_(warning)
            self.settings_info = self._label(NSMakeRect(20, 172, 670, 160), "", 11, secondary=True)
            self.settings_info.setSelectable_(True)
            self.settings_info.cell().setUsesSingleLineMode_(False)
            self.settings_info.cell().setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
            view.addSubview_(self.settings_info)
            self.model_settings_status = self._label(NSMakeRect(20, 118, 670, 46), "", 12)
            self.model_settings_status.cell().setUsesSingleLineMode_(False)
            self.model_settings_status.cell().setLineBreakMode_(AppKit.NSLineBreakByWordWrapping)
            view.addSubview_(self.model_settings_status)
            for x, width, title, action in ((20, 180, "重新检查当前依赖", "refreshDependencies:"),
                                           (454, 234, "保存模型配置（重启生效）", "saveModels:")):
                button = self._button(NSMakeRect(x, 68, width, 32), title, action)
                view.addSubview_(button)
                self.settings_controls.append(button)
            view.addSubview_(self._label(NSMakeRect(20, 20, 675, 36),
                "获取列表不发送聊天。测试只用虚构问候，不保存草稿；保存不测试、不切换当前客户端。", 11,
                secondary=True))
        self._load_model_form()
        self.settings_info.setStringValue_(self.runtime.settings_text())
        self.jev_switch.setState_(AppKit.NSControlStateValueOn if self.runtime.jev_enabled
                                  else AppKit.NSControlStateValueOff)
        self.settings_panel.makeKeyAndOrderFront_(None)
        AppKit.NSApplication.sharedApplication().activateIgnoringOtherApps_(True)

    @objc.python_method
    def _load_model_form(self):
        values = self._model_editor.public_values()
        self._editing_provider = values["reply_provider"]
        self._provider_forms = {}
        self.reply_protocol.selectItemWithTitle_(PROVIDERS[self._editing_provider])
        for target in ("jev", "reply"):
            prefix = "typesafe" if target == "jev" else "reply"
            for name in ("base", "model"):
                field = self.model_fields[(target, name)]
                field.setStringValue_(values[prefix + "_" + name])
                if name == "model":
                    field.removeAllItems()
                    field.addItemsWithObjectValues_([values[prefix + "_" + name]])
                    field.setStringValue_(values[prefix + "_" + name])
            self.model_fields[(target, "key")].setStringValue_("")
            self.model_clear[target].setState_(AppKit.NSControlStateValueOff)
            self.model_key_notes[target].setStringValue_("已保存密钥来源：" + self._model_editor.key_note(target))
        self.model_settings_status.setStringValue_("编辑的是已保存配置；下方显示当前运行状态。保存后需退出并重新打开应用。")

    @objc.python_method
    def _draft_form(self):
        values = {"reply_provider": self._editing_provider}
        for target in ("jev", "reply"):
            prefix = "typesafe" if target == "jev" else "reply"
            for name in ("base", "model"):
                values[prefix + "_" + name] = str(self.model_fields[(target, name)].stringValue())
        keys = {target: str(self.model_fields[(target, "key")].stringValue()) for target in ("jev", "reply")}
        clear = tuple(target for target in ("jev", "reply")
                      if self.model_clear[target].state() == AppKit.NSControlStateValueOn)
        return values, keys, clear

    def replyProtocolChanged_(self, sender):
        self._provider_forms[self._editing_provider] = (
            tuple(str(self.model_fields[("reply", name)].stringValue()) for name in ("base", "model", "key")),
            self.model_clear["reply"].state())
        self._editing_provider = next(key for key, label in PROVIDERS.items() if label == str(sender.titleOfSelectedItem()))
        default = ((PROVIDER_BASES[self._editing_provider],
                    "qwen3.5:4b" if self._editing_provider == "ollama" else "", ""), AppKit.NSControlStateValueOff)
        values, clear = self._provider_forms.get(self._editing_provider, default)
        self.model_fields[("reply", "model")].removeAllItems()
        for name, value in zip(("base", "model", "key"), values):
            self.model_fields[("reply", name)].setStringValue_(value)
        self.model_clear["reply"].setState_(clear)
        self.model_settings_status.setStringValue_("接口只改变当前草稿，保存并重启后才生效。")

    def settingsFieldChanged_(self, _sender):
        pass

    @objc.python_method
    def _start_model_task(self, sender, action):
        if self._settings_future is not None:
            return
        target = "jev" if sender.tag() == 0 else "reply"
        values, keys, clear = self._draft_form()
        try:
            self._model_editor.assert_unmodified()
            self._model_editor.preview(values, keys=keys, clear=clear, target=target,
                                       require_model=action == "test")
        except (OSError, ValueError) as error:
            self.model_settings_status.setStringValue_(settings_error(error))
            return
        operation = self._model_editor.list_models if action == "list" else self._model_editor.test
        self._settings_future = (self.runtime._pool.submit(operation, target, values, keys=keys, clear=clear),
                                 target, action)
        for control in self.settings_controls:
            control.setEnabled_(False)
        self.model_settings_status.setStringValue_("正在获取模型列表…" if action == "list" else "正在使用虚构问候测试草稿配置…")

    def listModels_(self, sender):
        self._start_model_task(sender, "list")

    def testDraft_(self, sender):
        self._start_model_task(sender, "test")

    @objc.python_method
    def _poll_model_task(self):
        if self._settings_future is None or not self._settings_future[0].done():
            return
        future, target, action = self._settings_future
        self._settings_future = None
        try:
            result = future.result()
            if action == "list":
                field = self.model_fields[(target, "model")]
                selected = str(field.stringValue())
                field.removeAllItems()
                field.addItemsWithObjectValues_(list(result))
                field.setStringValue_(selected)
                self.model_settings_status.setStringValue_(f"已获取 {len(result)} 个模型；可从下拉中选择，也可手动填写。")
            else:
                self.model_settings_status.setStringValue_("草稿测试：" + result.summary())
        except Exception as error:
            self.model_settings_status.setStringValue_(settings_error(error))

    def saveModels_(self, _sender):
        if self._settings_future is not None:
            return
        values, keys, clear = self._draft_form()
        try:
            candidate, _ = self._model_editor.preview(values, keys=keys, clear=clear)
            if (not is_loopback(candidate["reply_base"]) and
                    (candidate["reply_base"] != self._model_editor.config["reply_base"] or
                     candidate["reply_provider"] != self._model_editor.config["reply_provider"])):
                alert = AppKit.NSAlert.alloc().init()
                alert.setMessageText_("保存远端回复服务？")
                alert.setInformativeText_("重启并开始跟随后，当前聊天文本及上下文将发送至：\n"
                                          + candidate["reply_base"] + "\n关闭 Jev 判断不会关闭此回复服务。")
                alert.addButtonWithTitle_("保存")
                alert.addButtonWithTitle_("取消")
                if alert.runModal() != AppKit.NSAlertFirstButtonReturn:
                    return
            self._model_editor.save(values, keys=keys, clear=clear)
            self._load_model_form()
            self.model_settings_status.setStringValue_("已保存。当前客户端未切换，请退出并重新打开应用后生效。")
        except (OSError, ValueError) as error:
            self.model_settings_status.setStringValue_(settings_error(error))

    def toggleJev_(self, sender):
        enabled = sender.state() == AppKit.NSControlStateValueOn
        editor = getattr(self, "_model_editor", None)
        if editor:
            try:
                editor.assert_unmodified()
            except (OSError, ValueError) as error:
                sender.setState_(AppKit.NSControlStateValueOn if self.runtime.jev_enabled else AppKit.NSControlStateValueOff)
                self.model_settings_status.setStringValue_(settings_error(error))
                return
        if not self.runtime.set_jev_enabled(enabled):
            sender.setState_(AppKit.NSControlStateValueOn if self.runtime.jev_enabled
                             else AppKit.NSControlStateValueOff)
        if editor:
            try:
                editor.after_global_toggle()
            except (OSError, ValueError) as error:
                self.model_settings_status.setStringValue_(settings_error(error))
        self.settings_info.setStringValue_(self.runtime.settings_text())
        self._render(self.runtime.display())

    def refreshDependencies_(self, _sender):
        self.runtime.refresh_dependencies()

    def testLocal_(self, _sender):
        self.runtime.test_connection("ollama")

    def testJev_(self, _sender):
        self.runtime.test_connection("jev")

    def textDidBeginEditing_(self, _notification):
        self.runtime.set_overlay_focused(True)

    def textDidEndEditing_(self, _notification):
        if not self.panel.isKeyWindow():
            self.runtime.set_overlay_focused(False)

    def windowDidBecomeKey_(self, _notification):
        self.runtime.set_overlay_focused(True)

    def windowDidResignKey_(self, _notification):
        self.runtime.set_overlay_focused(False)

    def windowWillClose_(self, _notification):
        self.runtime.pause()
        if _notification and _notification.object() == self.settings_panel:
            self._settings_future = None
            self._provider_forms = {}
            for target in ("jev", "reply"):
                self.model_fields[(target, "key")].setStringValue_("")

    def quitApp_(self, _sender):
        self.runtime.close()
        AppKit.NSApplication.sharedApplication().terminate_(None)
