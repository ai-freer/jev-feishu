"""Explicit fallback to a user-entered conversation reference."""

from .types import ChatRef


def parse_manual_ref(value: str) -> ChatRef:
    text = value.strip()
    kind = "user" if text.startswith("ou_") else "chat"
    return ChatRef(kind, text)


def choose_manual_ref() -> ChatRef | None:
    import AppKit
    from Foundation import NSMakeRect

    alert = AppKit.NSAlert.alloc().init()
    alert.setMessageText_("手动指定测试会话")
    alert.setInformativeText_("请输入已确认的 chat ID（oc_…）或用户 open ID（ou_…）。手动模式仅用于联调或主动回退。")
    field = AppKit.NSTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 340, 26))
    alert.setAccessoryView_(field)
    alert.addButtonWithTitle_("进入手动模式")
    alert.addButtonWithTitle_("取消")
    if alert.runModal() != AppKit.NSAlertFirstButtonReturn:
        return None
    try:
        return parse_manual_ref(str(field.stringValue()))
    except ValueError:
        invalid = AppKit.NSAlert.alloc().init()
        invalid.setMessageText_("会话 ID 格式不正确")
        invalid.runModal()
        return None
