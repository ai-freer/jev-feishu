"""Read bounded visible bubbles from the verified chat pane."""

from dataclasses import dataclass


@dataclass(frozen=True, repr=False)
class VisibleMessage:
    token: str
    text: str
    own: bool
    top: int


def normalized(text):
    return "".join(text.replace("\u200b", "").split())


def bubble_text(subtree, read, descendants):
    rich = [n for n in subtree if "richTextContainer" in (read(n, "AXDOMClassList") or ())]
    if len(rich) != 1:
        return ""
    content = descendants(rich[0], 100)
    if content is None:
        return ""
    # Reactions and quote headers are outside the body and must not veto text.
    if any(read(n, "AXRole") == "AXImage" and
           "larkw-emoji__img" not in (read(n, "AXDOMClassList") or ()) for n in content):
        return ""
    parts = [read(n, "AXValue") for n in content if read(n, "AXRole") == "AXStaticText"]
    return "".join(parts) if parts and all(isinstance(v, str) for v in parts) else ""


def visible_bubbles(rows, bounds):
    x, y, width, height = bounds
    result = []
    for token, text, own, rect in rows:
        left, top, w, h = rect
        if (w > 0 and h > 4 and left >= x and left + w <= x + width + 1
                and top < y + height - 2 and top + h > y + 2):
            result.append(VisibleMessage(token, text, own, round(top)))
    return tuple(sorted(result, key=lambda row: row.top)[-8:])


def capture_visible(pane, header, read):
    import ApplicationServices as AX

    def rect(node):
        try:
            p_ok, p = AX.AXValueGetValue(read(node, "AXPosition"), AX.kAXValueCGPointType, None)
            s_ok, s = AX.AXValueGetValue(read(node, "AXSize"), AX.kAXValueCGSizeType, None)
            return (p.x, p.y, s.width, s.height) if p_ok and s_ok else None
        except (TypeError, ValueError, AttributeError):
            return None

    def descendants(root, limit=4000):
        stack = [(root, 0)]
        result = []
        while stack:
            node, depth = stack.pop()
            result.append(node)
            children = read(node, "AXChildren")
            if len(result) > limit or (children and (depth >= 45 or len(children) > 100)):
                return None
            stack.extend((child, depth + 1) for child in reversed(children or ()))
        return result

    nodes = descendants(pane)
    if nodes is None or header is None:
        return ()
    composers = [n for n in nodes if read(n, "AXRole") == "AXTextArea"]
    if len(composers) != 1:
        return ()
    area, head, composer = rect(pane), rect(header), rect(composers[0])
    if not area or not head or not composer:
        return ()
    top, bottom = head[1] + head[3], composer[1]
    if bottom <= top:
        return ()
    rows = []
    for node in nodes:
        classes = read(node, "AXDOMClassList") or ()
        if "MessageContextMenuTrigger" not in classes:
            continue
        own = "MessageContextMenuTrigger--scene-chatSelfMessage" in classes
        if not own and "MessageContextMenuTrigger--scene-chat" not in classes:
            continue
        token, frame = read(node, "AXDOMIdentifier"), rect(node)
        if not isinstance(token, str) or not token.isascii() or not token.isdigit() or not frame:
            continue
        subtree = descendants(node, 200)
        if subtree is None:
            return ()
        # Preserve unsupported bubbles as anchors: never jump above them.
        rows.append((token, bubble_text(subtree, read, descendants), own, frame))
    return visible_bubbles(rows, (area[0], top, area[2], bottom - top))
