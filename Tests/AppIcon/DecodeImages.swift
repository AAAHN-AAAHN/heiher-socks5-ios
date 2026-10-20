import CryptoKit
import Foundation
import ImageIO

/// Independent Apple decoder. This executable is test-only and never bundled.
@main struct DecodeImages {
    /// Sizes are derived from the compiler's standard point-size/scale filename.
    static func expectedPixels(_ name: String) throws -> Int {
        if name == "AppIcon.png" { return 1024 }
        let pattern = #"^AppIcon([0-9]+(?:\.[0-9]+)?)x\1(?:@([123])x)?(?:~(?:iphone|ipad))?\.png$"#
        let expression = try NSRegularExpression(pattern: pattern)
        guard let match = expression.firstMatch(in: name, range: NSRange(name.startIndex..., in: name)),
              let pointRange = Range(match.range(at: 1), in: name),
              let points = Double(name[pointRange]) else {
            throw NSError(domain: "IconFilename", code: 1)
        }
        let scaleRange = Range(match.range(at: 2), in: name)
        let scale = scaleRange.flatMap { Double(name[$0]) } ?? 1
        let pixels = points * scale
        guard pixels > 0, pixels <= 1024, pixels.rounded(.towardZero) == pixels else {
            throw NSError(domain: "IconDimensions", code: 1)
        }
        return Int(pixels)
    }

    static func main() throws {
        guard CommandLine.arguments.count > 1 else {
            throw NSError(domain: "IconInput", code: 1)
        }
        var results: [[String: Any]] = []
        for path in CommandLine.arguments.dropFirst() {
            let url = URL(fileURLWithPath: path)
            guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
                  let type = CGImageSourceGetType(source), type as String == "public.png",
                  CGImageSourceGetCount(source) == 1,
                  let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
                  CGImageSourceGetStatus(source) == .statusComplete else {
                throw NSError(domain: "IconDecode", code: 1, userInfo: [NSLocalizedDescriptionKey: path])
            }
            let width = image.width, height = image.height
            let expected = try expectedPixels(url.lastPathComponent)
            guard width == expected, height == expected else {
                throw NSError(domain: "IconDimensions", code: 1)
            }
            var pixels = [UInt8](repeating: 0, count: width * height * 4)
            try pixels.withUnsafeMutableBytes { bytes in
                guard let context = CGContext(data: bytes.baseAddress, width: width, height: height,
                    bitsPerComponent: 8, bytesPerRow: width * 4,
                    space: CGColorSpace(name: CGColorSpace.sRGB)!,
                    bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue) else {
                    throw NSError(domain: "IconContext", code: 1)
                }
                context.draw(image, in: CGRect(x: 0, y: 0, width: CGFloat(width), height: CGFloat(height)))
            }
            let opaque = stride(from: 3, to: pixels.count, by: 4).allSatisfy { pixels[$0] == 255 }
            guard opaque else { throw NSError(domain: "IconTransparency", code: 1) }
            let original = try Data(contentsOf: url)
            results.append(["name": url.lastPathComponent, "width": width, "height": height,
                "allPixelsOpaque": opaque, "frames": CGImageSourceGetCount(source),
                "bytes": original.count,
                "fileSHA256": SHA256.hash(data: original).map { String(format: "%02x", $0) }.joined(),
                "decodedRGBA_SHA256": SHA256.hash(data: Data(pixels)).map { String(format: "%02x", $0) }.joined(),
                "sourceAlphaInfo": image.alphaInfo.rawValue])
        }
        print(String(decoding: try JSONSerialization.data(withJSONObject: results,
                                                          options: [.sortedKeys, .prettyPrinted]), as: UTF8.self))
    }
}
