"""Entry point for the independent macOS status-bar companion."""

import AppKit
from Foundation import NSTimer

from .config import init_app_config
from .hud import HUDController
from .runtime import AppRuntime


def main():
    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    try:
        init_app_config()
        runtime = AppRuntime()
    except (OSError, ValueError):
        alert = AppKit.NSAlert.alloc().init()
        alert.setMessageText_("Jev 配置不可用")
        alert.setInformativeText_("请检查 ~/.config/jev-feishu/env 和 ~/.config/typesafe/env 的格式及权限。"
                                 "配置目录应为 0700、文件为 0600；密钥只保留在 TypeSafe 配置中。")
        alert.addButtonWithTitle_("退出")
        alert.runModal()
        return
    controller = HUDController.alloc().initWithRuntime_(runtime)
    app.setDelegate_(controller)
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.35, controller, "tick:", None, True)
    app.run()


if __name__ == "__main__":
    main()
