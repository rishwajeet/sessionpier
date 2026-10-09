import AppKit

// An independent, vector-drawn identity for the switcher, readable at Dock size.
// No Claude.app resources are modified or reused.
let output = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
try FileManager.default.createDirectory(at: output, withIntermediateDirectories: true)

func roundRect(_ rect: NSRect, _ radius: CGFloat, _ color: NSColor) {
    color.setFill()
    NSBezierPath(roundedRect: rect, xRadius: radius, yRadius: radius).fill()
}

func render(_ pixels: Int) -> Data {
    let rep = NSBitmapImageRep(bitmapDataPlanes: nil, pixelsWide: pixels, pixelsHigh: pixels,
                              bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true,
                              isPlanar: false, colorSpaceName: .deviceRGB,
                              bytesPerRow: 0, bitsPerPixel: 0)!
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)
    NSGraphicsContext.current?.imageInterpolation = .high
    let scale = CGFloat(pixels) / 1024
    let transform = NSAffineTransform()
    transform.scaleX(by: scale, yBy: scale)
    transform.concat()
    let tile = NSBezierPath(roundedRect: NSRect(x: 52, y: 52, width: 920, height: 920), xRadius: 208, yRadius: 208)
    NSGradient(starting: NSColor(srgbRed: 0.22, green: 0.24, blue: 0.63, alpha: 1),
               ending: NSColor(srgbRed: 0.09, green: 0.11, blue: 0.32, alpha: 1))!.draw(in: tile, angle: -80)
    // Three account cards: olive behind blue behind the light active account.
    roundRect(NSRect(x: 224, y: 312, width: 472, height: 464), 70,
              NSColor(srgbRed: 0.62, green: 0.65, blue: 0.38, alpha: 1))
    roundRect(NSRect(x: 292, y: 266, width: 472, height: 464), 70,
              NSColor(srgbRed: 0.36, green: 0.63, blue: 0.93, alpha: 1))
    roundRect(NSRect(x: 360, y: 220, width: 472, height: 464), 70,
              NSColor(srgbRed: 0.98, green: 0.95, blue: 0.89, alpha: 1))
    let ink = NSColor(srgbRed: 0.17, green: 0.20, blue: 0.49, alpha: 1)
    func arrow(_ points: [NSPoint]) {
        let path = NSBezierPath()
        path.move(to: points[0])
        for point in points.dropFirst() { path.line(to: point) }
        path.lineWidth = 37
        path.lineCapStyle = .round
        path.lineJoinStyle = .round
        ink.setStroke(); path.stroke()
    }
    arrow([NSPoint(x: 458, y: 516), NSPoint(x: 728, y: 516)])
    arrow([NSPoint(x: 671, y: 573), NSPoint(x: 728, y: 516), NSPoint(x: 671, y: 459)])
    arrow([NSPoint(x: 730, y: 386), NSPoint(x: 460, y: 386)])
    arrow([NSPoint(x: 517, y: 443), NSPoint(x: 460, y: 386), NSPoint(x: 517, y: 329)])
    NSGraphicsContext.restoreGraphicsState()
    return rep.representation(using: .png, properties: [:])!
}

for size in [16, 32, 128, 256, 512] {
    try render(size).write(to: output.appendingPathComponent("icon_\(size)x\(size).png"))
    try render(size * 2).write(to: output.appendingPathComponent("icon_\(size)x\(size)@2x.png"))
}
