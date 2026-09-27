"""Render the original Jev Feishu icon using macOS graphics; no network or fonts."""

from pathlib import Path
import argparse
import subprocess
import tempfile

import AppKit as A
from Foundation import NSAffineTransform, NSMakeRect


BUBBLE = (
    ('M', 330, 250), ('L', 694, 250), ('C', 758, 250, 808, 300, 808, 364),
    ('L', 808, 620), ('C', 808, 684, 758, 734, 694, 734), ('L', 443, 734),
    ('L', 337, 812), ('L', 337, 734), ('L', 330, 734),
    ('C', 266, 734, 216, 684, 216, 620), ('L', 216, 364),
    ('C', 216, 300, 266, 250, 330, 250), ('Z',),
)
LETTER = (('M', 597, 392), ('L', 597, 541), ('C', 597, 601, 563, 637, 510, 637),
          ('C', 466, 637, 434, 615, 417, 580))
CAP = (('M', 537, 392), ('L', 654, 392))


def color(red, green, blue, alpha=1):
    return A.NSColor.colorWithSRGBRed_green_blue_alpha_(red / 255, green / 255, blue / 255, alpha)


def path(commands):
    result = A.NSBezierPath.bezierPath()
    for command, *points in commands:
        if command == 'M':
            result.moveToPoint_(tuple(points))
        elif command == 'L':
            result.lineToPoint_(tuple(points))
        elif command == 'C':
            result.curveToPoint_controlPoint1_controlPoint2_(tuple(points[4:]), tuple(points[:2]), tuple(points[2:4]))
        elif command == 'Z':
            result.closePath()
    return result


def render(size):
    bitmap = A.NSBitmapImageRep.alloc().initWithBitmapDataPlanes_pixelsWide_pixelsHigh_bitsPerSample_samplesPerPixel_hasAlpha_isPlanar_colorSpaceName_bytesPerRow_bitsPerPixel_(
        None, size, size, 8, 4, True, False, A.NSCalibratedRGBColorSpace, 0, 0)
    A.NSGraphicsContext.saveGraphicsState()
    try:
        context = A.NSGraphicsContext.graphicsContextWithBitmapImageRep_(bitmap)
        A.NSGraphicsContext.setCurrentContext_(context)
        context.setShouldAntialias_(True)
        A.NSColor.clearColor().set()
        A.NSRectFillUsingOperation(NSMakeRect(0, 0, size, size), A.NSCompositingOperationCopy)
        transform = NSAffineTransform.transform()
        transform.translateXBy_yBy_(0, size)
        transform.scaleXBy_yBy_(size / 1024, -size / 1024)
        transform.concat()
        tile = A.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(NSMakeRect(64, 64, 896, 896), 204, 204)
        A.NSGraphicsContext.saveGraphicsState()
        shadow = A.NSShadow.alloc().init()
        shadow.setShadowColor_(color(16, 42, 105, .24))
        shadow.setShadowBlurRadius_(22)
        shadow.setShadowOffset_((0, 12))
        shadow.set()
        color(36, 80, 199).setFill()
        tile.fill()
        A.NSGraphicsContext.restoreGraphicsState()
        gradient = A.NSGradient.alloc().initWithStartingColor_endingColor_(color(53, 122, 255), color(35, 71, 187))
        gradient.drawInBezierPath_angle_(tile, 90)
        color(255, 255, 255, .18).setStroke()
        tile.setLineWidth_(2)
        tile.stroke()
        color(255, 255, 255).setFill()
        path(BUBBLE).fill()
        color(34, 83, 196).setStroke()
        for commands in (CAP, LETTER):
            stroke = path(commands)
            stroke.setLineWidth_(66)
            stroke.setLineCapStyle_(A.NSRoundLineCapStyle)
            stroke.setLineJoinStyle_(A.NSRoundLineJoinStyle)
            stroke.stroke()
        color(40, 192, 168).setFill()
        A.NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(354, 357, 70, 70)).fill()
        return bytes(bitmap.representationUsingType_properties_(A.NSPNGFileType, {}))
    finally:
        A.NSGraphicsContext.restoreGraphicsState()


def svg():
    def data(commands):
        return ' '.join(' '.join(map(str, command)) for command in commands)
    return f'''<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <title>Jev Feishu — original conversation and J mark</title>
  <defs>
    <linearGradient id="tile" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#357aff"/><stop offset="1" stop-color="#2347bb"/></linearGradient>
    <filter id="shadow" x="-10%" y="-10%" width="120%" height="125%"><feDropShadow dx="0" dy="12" stdDeviation="11" flood-color="#102a69" flood-opacity=".24"/></filter>
  </defs>
  <rect x="64" y="64" width="896" height="896" rx="204" fill="url(#tile)" stroke="#fff" stroke-opacity=".18" stroke-width="2" filter="url(#shadow)"/>
  <path d="{data(BUBBLE)}" fill="#fff"/>
  <path d="{data(CAP)} {data(LETTER)}" fill="none" stroke="#2253c4" stroke-width="66" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="389" cy="392" r="35" fill="#28c0a8"/>
</svg>
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=Path(__file__).resolve().parent / 'assets')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / 'JevFeishu.svg').write_text(svg())
    (output / 'JevFeishu.png').write_bytes(render(1024))
    with tempfile.TemporaryDirectory(prefix='jev-icon-') as tmp:
        iconset = Path(tmp) / 'JevFeishu.iconset'
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                suffix = '@2x' if scale == 2 else ''
                (iconset / f'icon_{size}x{size}{suffix}.png').write_bytes(render(size * scale))
        subprocess.run(['iconutil', '-c', 'icns', str(iconset), '-o', str(output / 'JevFeishu.icns')], check=True)
    print('Generated original SVG, 1024px PNG and multi-resolution ICNS')


if __name__ == '__main__':
    main()
