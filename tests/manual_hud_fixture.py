"""Exercise installed modules with fictional boundaries, without real CLI or HTTP calls.

Run with /Applications/Jev 飞书助手.app/Contents/MacOS/JevFeishuPython -B.
Use --check for a bounded runtime check; omit it for the native HUD and fixture controls.
"""

import argparse
from pathlib import Path
import time

from fixture_scenario import FixtureScenario


def wait_for(runtime, predicate):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        runtime.pulse()
        if predicate(runtime.display()):
            return
        time.sleep(0.01)
    raise AssertionError("fictional packaged runtime did not reach expected state")


def check(runtime, scenario):
    runtime.start()
    wait_for(runtime, lambda state: state.result is not None)
    assert len(runtime.display().result.replies) == 6
    assert runtime.display().cloud_enabled
    assert any(kind == "jev" for kind, _model in scenario.model_calls)
    assert runtime.set_jev_enabled(False)
    wait_for(runtime, lambda state: state.result is not None)
    cloud_calls = sum(kind == "jev" for kind, _model in scenario.model_calls)
    scenario.switch("b")
    wait_for(runtime, lambda state: state.chat_title == scenario.title and state.result is not None)
    assert len(runtime.display().result.replies) == 6
    assert not runtime.display().cloud_enabled
    assert sum(kind == "jev" for kind, _model in scenario.model_calls) == cloud_calls
    assert runtime.set_jev_enabled(True)
    wait_for(runtime, lambda state: bool(state.result and state.result.verdict))
    scenario.local_error = "connection_error"
    runtime.retry_current()
    wait_for(runtime, lambda state: state.status == "connection_error")
    assert not runtime.display().result.replies
    scenario.local_error = None
    runtime.retry_current()
    wait_for(runtime, lambda state: bool(state.result and len(state.result.replies) == 6))
    scenario.leave()
    wait_for(runtime, lambda state: state.status == "unidentified")
    assert runtime.display().result is None
    scenario.authorized = False
    runtime.refresh_dependencies()
    wait_for(runtime, lambda state: state.status == "lark_auth_unavailable")
    assert not runtime.can_start
    runtime.close()
    reads = scenario.read_count
    runtime.start()
    runtime.pulse()
    assert scenario.read_count == reads
    print("installed_modules=verified fictional_pipeline=passed candidates=6 cloud_default=on")


def show_hud(runtime, scenario):
    import AppKit
    from Foundation import NSObject, NSMakeRect, NSTimer
    from jev_feishu.hud import HUDController

    class FixtureControls(NSObject):
        def change_(self, sender):
            action = sender.tag()
            runtime.set_overlay_focused(False)
            if action in (0, 1):
                scenario.switch("a" if action == 0 else "b")
            elif action == 2:
                scenario.leave()
            elif action == 3:
                scenario.revision += 1
            elif action == 4:
                scenario.deleted = True
            elif action == 5:
                scenario.local_error = "connection_error" if scenario.local_error is None else None
            elif action in (6, 7):
                scenario.authorized = action == 7
                runtime.refresh_dependencies()
            self.info.setStringValue_(
                f"虚构场景：{scenario.title} / {scenario.page}；"
                f"本机模型 {'异常' if scenario.local_error else '正常'}")

    app = AppKit.NSApplication.sharedApplication()
    app.setActivationPolicy_(AppKit.NSApplicationActivationPolicyAccessory)
    hud = HUDController.alloc().initWithRuntime_(runtime)
    app.setDelegate_(hud)
    hud.panel.setTitle_("Jev 飞书助手 · 虚构验收")
    controls = FixtureControls.alloc().init()
    controls.panel = AppKit.NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(30, 80, 520, 190), AppKit.NSWindowStyleMaskTitled,
        AppKit.NSBackingStoreBuffered, False)
    controls.panel.setTitle_("虚构测试控制台（无真实 CLI / 网络）")
    controls.panel.setLevel_(AppKit.NSFloatingWindowLevel)
    controls.panel.setHidesOnDeactivate_(False)
    view = controls.panel.contentView()
    labels = ("单聊 A", "普通群 B", "离开飞书", "编辑消息", "撤回消息",
              "切换模型故障", "授权失效", "恢复授权")
    for index, title in enumerate(labels):
        button = AppKit.NSButton.alloc().initWithFrame_(
            NSMakeRect(10 + index % 4 * 128, 126 - index // 4 * 42, 125, 32))
        button.setTitle_(title)
        button.setTarget_(controls)
        button.setAction_("change:")
        button.setTag_(index)
        view.addSubview_(button)
    controls.info = AppKit.NSTextField.labelWithString_("虚构场景就绪；请在悬浮窗点击开始跟随。")
    controls.info.setFrame_(NSMakeRect(14, 20, 492, 40))
    view.addSubview_(controls.info)
    controls.panel.orderFrontRegardless()
    NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.35, hud, "tick:", None, True)
    app.run()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    import jev_feishu.runtime

    installed = Path("/Applications/Jev 飞书助手.app/Contents/lib/python3.12/site-packages/jev_feishu")
    assert Path(jev_feishu.runtime.__file__).resolve().is_relative_to(installed)
    scenario = FixtureScenario(package="jev_feishu")
    runtime = scenario.make_runtime()
    try:
        if args.check:
            check(runtime, scenario)
        else:
            show_hud(runtime, scenario)
    finally:
        runtime.close()
        scenario.close()


if __name__ == "__main__":
    main()
