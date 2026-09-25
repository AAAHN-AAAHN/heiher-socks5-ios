import CryptoKit
import Foundation
import ImageIO

/// Independent Apple decoder. This executable is test-only and never bundled.
@main struct DecodeImages {
    static func main() throws {
        var results: [[String: Any]] = []
        for path in CommandLine.arguments.dropFirst() {
            let url = URL(fileURLWithPath: path)
            guard let source = CGImageSourceCreateWithURL(url as CFURL, nil),
                  CGImageSourceGetCount(source) == 1,
                  let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
                  CGImageSourceGetStatus(source) == .statusComplete else {
                throw NSError(domain: "IconDecode", code: 1, userInfo: [NSLocalizedDescriptionKey: path])
            }
            let width = image.width, height = image.height
            guard width > 0, width <= 1024, width == height else {
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
