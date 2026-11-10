// 本地macOS Vision适配器：PNG -> 原始候选与坐标JSON，不执行入库或内容修订。
import Foundation
import Vision
import ImageIO

func emit(_ value: [String: Any]) throws {
    let data = try JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes])
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data("\n".utf8))
}

do {
    let request = VNRecognizeTextRequest()
    request.revision = VNRecognizeTextRequestRevision3
    request.recognitionLevel = .accurate
    request.recognitionLanguages = ["zh-Hans", "en-US"]
    request.usesLanguageCorrection = false
    request.minimumTextHeight = 0
    let supported = try request.supportedRecognitionLanguages()
    let config: [String: Any] = [
        "engine": "macOS Vision VNRecognizeTextRequest", "revision": request.revision,
        "recognition_level": "accurate", "languages": request.recognitionLanguages,
        "uses_language_correction": request.usesLanguageCorrection,
        "minimum_text_height": request.minimumTextHeight,
        "os_version": ProcessInfo.processInfo.operatingSystemVersionString,
        "supported_languages": supported
    ]
    guard supported.contains("zh-Hans") else {
        throw NSError(domain: "VisionOCR", code: 1, userInfo: [NSLocalizedDescriptionKey: "Vision当前修订不支持简体中文"])
    }
    if CommandLine.arguments.count == 2 && CommandLine.arguments[1] == "--probe" {
        try emit(["status": "available", "configuration": config])
    } else {
        guard CommandLine.arguments.count == 2 else {
            throw NSError(domain: "VisionOCR", code: 2, userInfo: [NSLocalizedDescriptionKey: "用法: vision_ocr PNG路径 或 --probe"])
        }
        let imageURL = URL(fileURLWithPath: CommandLine.arguments[1])
        guard let source = CGImageSourceCreateWithURL(imageURL as CFURL, nil),
              let properties = CGImageSourceCopyPropertiesAtIndex(source, 0, nil) as? [CFString: Any],
              let width = properties[kCGImagePropertyPixelWidth] as? Int,
              let height = properties[kCGImagePropertyPixelHeight] as? Int else {
            throw NSError(domain: "VisionOCR", code: 3, userInfo: [NSLocalizedDescriptionKey: "无法读取PNG尺寸"])
        }
        let started = Date()
        let handler = VNImageRequestHandler(url: imageURL, options: [:])
        try handler.perform([request])
        let observations: [[String: Any]] = (request.results ?? []).enumerated().map { index, observation in
            let box = observation.boundingBox
            return [
                "observation_id": index,
                "vision_normalized_bbox": [box.origin.x, box.origin.y, box.width, box.height],
                "pixel_bbox_top_left": [box.minX * Double(width), (1 - box.maxY) * Double(height), box.maxX * Double(width), (1 - box.minY) * Double(height)],
                "candidates": observation.topCandidates(3).map { ["text": $0.string, "confidence": $0.confidence] as [String: Any] }
            ]
        }
        try emit(["status": "ok", "configuration": config,
                  "image_width": width, "image_height": height,
                  "elapsed_seconds": Date().timeIntervalSince(started), "observations": observations])
    }
} catch {
    try? emit(["status": "error", "error": String(describing: error)])
    exit(1)
}
