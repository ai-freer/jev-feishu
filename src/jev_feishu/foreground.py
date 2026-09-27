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

    def complete_header_scope(title_node, title_branch):
        # Only this fully read desktop header gives an empty badge slot meaning.
        # A missing marker in an arbitrary or truncated AX tree is still unknown.
        if title_branch is None or read(title_branch, AX.kAXRoleAttribute) != "AXGroup":
            return None
        children = read(title_branch, AX.kAXChildrenAttribute)
        if children is None or not 6 <= len(children) <= 7 or children[0] != title_node:
            return None

        def subtree(node, depth=0):
            if depth > 4:
                return None
            role = read(node, AX.kAXRoleAttribute)
            if role not in ("AXGroup", "AXStaticText", "AXButton", "AXImage"):
                return None
            try:
                status, nested = AX.AXUIElementCopyAttributeValue(node, AX.kAXChildrenAttribute, None)
            except Exception:
                return None
            if status != 0:
                if status != AX.kAXErrorAttributeUnsupported or role == "AXGroup":
                    return None
                nested = None
            if nested is None and role == "AXGroup":
                return None
            if nested is not None and len(nested) > 12:
                return None
            rows = [(role, read(node, AX.kAXValueAttribute), read(node, AX.kAXTitleAttribute),
                     read(node, AX.kAXDescriptionAttribute))]
            if role == "AXStaticText" and not isinstance(rows[0][1], str):
                return None
            for child in nested or ():
                result = subtree(child, depth + 1)
                if result is None:
                    return None
                rows.extend(result)
                if len(rows) > 80:
                    return None
            return rows

        parts = [subtree(child) for child in children[1:]]
        if any(part is None for part in parts):
            return None
        badge = [part for part in parts if any(row[0] == "AXStaticText" and row[1] == "外部"
                                              for row in part)]
        if badge:
            return True
        if len(children) != 6:
            return None
        toolbar, *tabs, trailing = parts
        if (read(children[1], AX.kAXRoleAttribute) != "AXGroup"
                or any(row[0] == "AXStaticText" for row in toolbar)
                or sum(row[0] == "AXButton" for row in toolbar) < 3
                or not any(row[0] == "AXButton" and "doubao avatar" in row[2:]
                           for row in toolbar)):
            return None
        for part, caption in zip(tabs, ("消息", "云文档", "文件")):
            if (part[0][0] != "AXGroup"
                    or [row[1] for row in part if row[0] == "AXStaticText"] != [caption]
                    or not any(row[0] == "AXImage" for row in part)):
                return None
        if len(trailing) != 1 or trailing[0][0] != "AXImage":
            return None
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
                else:
                    external = complete_header_scope(node, parent)
        elif role == "AXTextArea":
            recipient_value = read(node, AX.kAXValueAttribute)
    matched = bool(title and isinstance(recipient_value, str)
                   and f"发送给 {title}" in recipient_value)
    if not matched:
        return bundle, "unknown", 1, None, False, None
    return bundle, "chat", 1, title, True, external
