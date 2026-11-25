// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//
// The picture of an .igz in Finder, the open and save dialogs and Quick
// Look on macOS: a thumbnail extension (QLThumbnailProvider) inside
// IngeTrazo.app, the counterpart of the Windows handler (installer/thumbnail).
//
// It shows the thumbnail.png IngeTrazo stores in the document when it saves
// it (IgzThumbnail.swift reads it, never the model), decoded by ImageIO and
// fitted inside the size asked for, never enlarged. A document without a
// picture gets an error back, and Finder shows the document icon instead.
// Built and embedded by build.sh; the system runs it sandboxed, in a
// process of its own.

import CoreGraphics
import Foundation
import ImageIO
import QuickLookThumbnailing

final class ThumbnailProvider: QLThumbnailProvider {
    static let maxSide = 4096                       // pixels

    override func provideThumbnail(
        for request: QLFileThumbnailRequest,
        _ handler: @escaping (QLThumbnailReply?, Error?) -> Void
    ) {
        guard let image = Self.picture(at: request.fileURL) else {
            handler(nil, CocoaError(.fileReadCorruptFile))
            return
        }
        let w = CGFloat(image.width), h = CGFloat(image.height)
        let box = request.maximumSize
        let scale = min(box.width / w, box.height / h, 1.0)
        let size = CGSize(width: max(1, (w * scale).rounded()),
                          height: max(1, (h * scale).rounded()))
        handler(QLThumbnailReply(contextSize: size) { context in
            Self.draw(image, into: context)
            return true
        }, nil)
    }

    /// The picture over the whole of `context`. The context is the size
    /// asked for times the screen's scale, in pixels and not scaled: drawn
    /// at the size asked for, the picture took a quarter of a Retina
    /// thumbnail.
    static func draw(_ image: CGImage, into context: CGContext) {
        context.interpolationQuality = .high
        context.draw(image, in: CGRect(x: 0, y: 0, width: context.width,
                                       height: context.height))
    }

    /// The document's picture decoded as a PNG, or nil.
    static func picture(at url: URL) -> CGImage? {
        guard let png = IgzThumbnail.png(at: url) else { return nil }
        let options = [kCGImageSourceTypeIdentifierHint: "public.png"] as CFDictionary
        guard let source = CGImageSourceCreateWithData(png as CFData, options),
              CGImageSourceGetType(source) as String? == "public.png",
              let image = CGImageSourceCreateImageAtIndex(source, 0, nil),
              image.width > 0, image.height > 0,
              image.width <= maxSide, image.height <= maxSide
        else { return nil }
        return image
    }
}
