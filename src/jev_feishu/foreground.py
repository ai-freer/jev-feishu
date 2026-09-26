"""Observed foreground state. The live AX probe must supply verified evidence."""

from dataclasses import dataclass
from threading import Lock
from typing import Literal

from .types import ChatRef


@dataclass(frozen=True, repr=False)
class ChatEvidence:
    ref: ChatRef
    selected: bool
    api_confirmed: bool


@dataclass(frozen=True, repr=False)
class ChatObservation:
    epoch: int
    frontmost_bundle: str | None
    page: Literal["chat", "other", "unknown", "permission_required"]
    window_count: int
    candidates: tuple[ChatEvidence, ...] = ()
    title: str | None = None
    recipient_matches_title: bool = False
    external: bool | None = None

    def __post_init__(self):
        if type(self.epoch) is not int or self.epoch < 0:
            raise ValueError("invalid_epoch")
        if self.page not in ("chat", "other", "unknown", "permission_required"):
            raise ValueError("invalid_page")
        if type(self.window_count) is not int or self.window_count < 0:
            raise ValueError("invalid_window_count")
        if self.external is not None and type(self.external) is not bool:
            raise ValueError("invalid_external_evidence")


def invalid_observation(epoch: int, bundle: str | None = None) -> ChatObservation:
    return ChatObservation(epoch, bundle, "unknown", 0)


class ForegroundProbe:
    """Read only AX metadata for the active Lark chat; never capture screenshots."""

    def __init__(self, surface=None):
        self._surface = surface or _mac_surface
        self._signature = None
        self._epoch = 0
        self._lock = Lock()

    def observe(self) -> ChatObservation:
        with self._lock:
            surface = self._surface()
            if len(surface) == 5:
                surface = (*surface, None)
            bundle, page, windows, title, recipient_match, external = surface
            signature = (bundle, page, windows, title, recipient_match, external)
            if signature != self._signature:
                self._epoch += 1
                self._signature = signature
            return ChatObservation(self._epoch, bundle, page, windows, (), title, recipient_match, external)


def _mac_surface(workspace=None):
    import ApplicationServices as AX
    from AppKit import NSWorkspace

    workspace = workspace or NSWorkspace.sharedWorkspace()
    app = workspace.frontmostApplication()
    bundle = app.bundleIdentifier() if app else None
    if bundle != "com.electron.lark":
        return bundle, "unknown", 0, None, False, None
    if not AX.AXIsProcessTrusted():
        return bundle, "permission_required", 0, None, False, None

    def read(element, name):
        try:
            status, value = AX.AXUIElementCopyAttributeValue(element, name, None)
            return value if status == 0 else None
        except Exception:
            return None

    root = AX.AXUIElementCreateApplication(app.processIdentifier())
    AX.AXUIElementSetMessagingTimeout(root, 0.5)
    windows = read(root, AX.kAXWindowsAttribute)
    if windows is None:
        return bundle, "unknown", 0, None, False, None
    standard = [window for window in windows
                if read(window, AX.kAXSubroleAttribute) == "AXStandardWindow"
                and read(window, AX.kAXMinimizedAttribute) is not True]
    if len(standard) != 1:
        return bundle, "unknown", len(standard), None, False, None
    main = standard[0]
    if read(main, AX.kAXMainAttribute) is not True:
        return bundle, "unknown", 1, None, False, None

    def walk(element, depth_limit=30, max_nodes=1600):
        stack = [(element, 0, None, None)]
        visited = 0
        while stack and visited < max_nodes:
            node, depth, parent, grandparent = stack.pop()
            visited += 1
            yield node, parent, grandparent
            if depth < depth_limit:
                children = read(node, AX.kAXChildrenAttribute)
                if children is not None:
                    try:
                        stack.extend((child, depth + 1, node, parent)
                                     for child in reversed(list(children)[:100]))
                    except TypeError:
                        pass

    panes = [node for node, _, _ in walk(main, 15)
             if read(node, AX.kAXRoleAttribute) == "AXWebArea"
             and read(node, AX.kAXTitleAttribute) == "messenger-chat"]
    if len(panes) != 1:
        return bundle, "other", 1, None, False, None

    def has_external_badge(header, title_branch):
        if header is None or title_branch is None:
            return False
        branches = read(header, AX.kAXChildrenAttribute)
        if branches is None or len(branches) > 12 or title_branch not in branches:
            return False
        for branch in branches:
            if branch == title_branch:
                continue
            for node, _, _ in walk(branch, 3, 40):
                if (read(node, AX.kAXRoleAttribute) == "AXStaticText"
                        and read(node, AX.kAXValueAttribute) == "外部"):
                    return True
        return False

    title = None
    external = None
    recipient_value = None
    for node, parent, header in walk(panes[0]):
        role = read(node, AX.kAXRoleAttribute)
        if role == "AXStaticText" and title is None:
            value = read(node, AX.kAXValueAttribute)
            if isinstance(value, str) and value.strip():
                title = value.strip()
                if has_external_badge(header, parent):
                    external = True
        elif role == "AXTextArea":
            recipient_value = read(node, AX.kAXValueAttribute)
    matched = bool(title and isinstance(recipient_value, str)
                   and f"发送给 {title}" in recipient_value)
    if not matched:
        return bundle, "unknown", 1, None, False, None
    return bundle, "chat", 1, title, True, external
