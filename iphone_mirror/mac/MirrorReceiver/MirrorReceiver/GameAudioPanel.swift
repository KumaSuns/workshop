import AppKit

final class GameAudioPanel: NSView {
    private let blocks = 12
    private(set) var volume = 100
    private(set) var muted = false
    var onChange: (() -> Void)?

    override var isFlipped: Bool { true }

    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }

    override func resetCursorRects() {
        addCursorRect(bounds, cursor: .pointingHand)
    }

    override func mouseDown(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        if muteBounds().contains(point) {
            muted.toggle()
            needsDisplay = true
            onChange?()
            return
        }
        if meterBounds().contains(point) {
            setVolume(from: point.y)
        }
    }

    override func mouseDragged(with event: NSEvent) {
        let point = convert(event.locationInWindow, from: nil)
        if !muteBounds().contains(point) {
            setVolume(from: point.y)
        }
    }

    private func setVolume(from y: CGFloat) {
        let meter = meterBounds()
        let span = max(1, meter.height)
        let amount = (meter.maxY - y) / span
        let next = Int((amount * 100).rounded())
        let clamped = min(100, max(0, next))
        guard clamped != volume else { return }
        volume = clamped
        needsDisplay = true
        onChange?()
    }

    private func meterBounds() -> NSRect {
        let top: CGFloat = 78
        let bottom = bounds.height - 86
        return NSRect(x: 30, y: top, width: bounds.width - 60, height: max(40, bottom - top))
    }

    private func muteBounds() -> NSRect {
        NSRect(x: 10, y: bounds.height - 72, width: bounds.width - 20, height: 56)
    }

    override func draw(_ dirtyRect: NSRect) {
        NSColor(srgbRed: 8 / 255, green: 12 / 255, blue: 22 / 255, alpha: 1).setFill()
        bounds.fill()

        NSColor(srgbRed: 80 / 255, green: 255 / 255, blue: 214 / 255, alpha: 0.28).setStroke()
        let edge = NSBezierPath(rect: bounds.insetBy(dx: 1, dy: 1))
        edge.lineWidth = 2
        edge.stroke()

        let accent = muted
            ? NSColor(srgbRed: 1, green: 84 / 255, blue: 112 / 255, alpha: 1)
            : NSColor(srgbRed: 80 / 255, green: 1, blue: 214 / 255, alpha: 1)
        draw("音量", in: NSRect(x: 0, y: 14, width: bounds.width, height: 20), size: 13, color: accent)
        let numberColor = muted
            ? NSColor(srgbRed: 1, green: 140 / 255, blue: 156 / 255, alpha: 1)
            : NSColor.white
        draw(muted ? "--" : "\(volume)", in: NSRect(x: 0, y: 36, width: bounds.width, height: 34), size: 28, color: numberColor)
        drawMeter()
        drawMute()
    }

    private func drawMeter() {
        let meter = meterBounds()
        let gap: CGFloat = 4
        let block = max(6, (meter.height - gap * CGFloat(blocks - 1)) / CGFloat(blocks))
        let lit = muted ? 0 : Int((Double(volume) / 100 * Double(blocks)).rounded())
        for index in 0..<blocks {
            let y = meter.maxY - CGFloat(index + 1) * block - CGFloat(index) * gap
            let cell = NSRect(x: meter.minX, y: y, width: meter.width, height: block)
            let color = index < lit ? blockColor(index) : NSColor(srgbRed: 26 / 255, green: 34 / 255, blue: 52 / 255, alpha: 1)
            color.setFill()
            cell.fill()
        }
    }

    private func blockColor(_ index: Int) -> NSColor {
        let t = CGFloat(index) / CGFloat(blocks - 1)
        return NSColor(
            srgbRed: (80 + (255 - 80) * t) / 255,
            green: (255 + (70 - 255) * t) / 255,
            blue: (214 + (170 - 214) * t) / 255,
            alpha: 1
        )
    }

    private func drawMute() {
        let bounds = muteBounds()
        let fill = muted
            ? NSColor(srgbRed: 186 / 255, green: 32 / 255, blue: 64 / 255, alpha: 1)
            : NSColor(srgbRed: 16 / 255, green: 40 / 255, blue: 48 / 255, alpha: 1)
        let line = muted
            ? NSColor(srgbRed: 1, green: 120 / 255, blue: 140 / 255, alpha: 1)
            : NSColor(srgbRed: 80 / 255, green: 1, blue: 214 / 255, alpha: 1)
        fill.setFill()
        bounds.fill()
        line.setStroke()
        let path = NSBezierPath(rect: bounds)
        path.lineWidth = 2
        path.stroke()
        draw(muted ? "消音中" : "消音", in: bounds, size: 16, color: .white)
    }

    private func draw(_ text: String, in rect: NSRect, size: CGFloat, color: NSColor) {
        let style = NSMutableParagraphStyle()
        style.alignment = .center
        let attrs: [NSAttributedString.Key: Any] = [
            .font: NSFont.boldSystemFont(ofSize: size),
            .foregroundColor: color,
            .paragraphStyle: style,
        ]
        let textSize = (text as NSString).size(withAttributes: attrs)
        let textRect = NSRect(
            x: rect.minX,
            y: rect.midY - textSize.height / 2,
            width: rect.width,
            height: textSize.height
        )
        (text as NSString).draw(in: textRect, withAttributes: attrs)
    }
}
