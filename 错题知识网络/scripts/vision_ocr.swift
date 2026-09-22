import AppKit
import Foundation
import Vision

func jsonEscape(_ value: String) -> String {
    let data = try! JSONSerialization.data(withJSONObject: value, options: [.fragmentsAllowed])
    return String(data: data, encoding: .utf8)!
}

let request = VNRecognizeTextRequest()
request.recognitionLanguages = ["zh-Hans", "en-US"]
request.recognitionLevel = .accurate
request.usesLanguageCorrection = true

while let line = readLine() {
    let path = line.trimmingCharacters(in: .whitespacesAndNewlines)
    if path.isEmpty {
        continue
    }

    var text = ""
    var errorMessage = ""
    do {
        let url = URL(fileURLWithPath: path)
        guard
            let image = NSImage(contentsOf: url),
            let tiff = image.tiffRepresentation,
            let bitmap = NSBitmapImageRep(data: tiff),
            let cgImage = bitmap.cgImage
        else {
            throw NSError(domain: "WrongNetOCR", code: 1, userInfo: [NSLocalizedDescriptionKey: "cannot load image"])
        }

        let handler = VNImageRequestHandler(cgImage: cgImage, options: [:])
        try handler.perform([request])
        let lines = (request.results ?? []).compactMap { $0.topCandidates(1).first?.string }
        text = lines.joined(separator: "\n")
    } catch let caughtError {
        errorMessage = String(describing: caughtError)
    }

    print("{\"path\":\(jsonEscape(path)),\"text\":\(jsonEscape(text)),\"error\":\(jsonEscape(errorMessage))}")
    fflush(stdout)
}
