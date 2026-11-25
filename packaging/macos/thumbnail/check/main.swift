// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//
// The extension's reading, from the command line, for the tests
// (tests/test_macos_igz_thumbnail.py):
//
//     igz-thumbnail-check document.igz out.png [drawn.png]
//
// Writes the bytes the extension would show and prints the decoded size;
// exits 1 when the extension would show the document icon instead. With
// drawn.png, also draws the picture as the extension does into a context
// twice its size, as a Retina thumbnail is, and writes that.
// Built with ../ThumbnailProvider.swift and ../IgzThumbnail.swift.

import CoreGraphics
import Foundation
import ImageIO

let args = CommandLine.arguments
guard args.count == 3 || args.count == 4 else {
    FileHandle.standardError.write("usage: igz-thumbnail-check document.igz out.png [drawn.png]\n".data(using: .utf8)!)
    exit(2)
}
let url = URL(fileURLWithPath: args[1])
guard let png = IgzThumbnail.png(at: url), let image = ThumbnailProvider.picture(at: url) else {
    print("none")
    exit(1)
}
try png.write(to: URL(fileURLWithPath: args[2]))
print("\(image.width)x\(image.height)")
if args.count == 4 {
    let w = image.width * 2, h = image.height * 2
    guard let ctx = CGContext(data: nil, width: w, height: h, bitsPerComponent: 8,
                              bytesPerRow: 0, space: CGColorSpaceCreateDeviceRGB(),
                              bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
    else { exit(3) }
    ThumbnailProvider.draw(image, into: ctx)
    guard let drawn = ctx.makeImage(),
          let dest = CGImageDestinationCreateWithURL(
              URL(fileURLWithPath: args[3]) as CFURL, "public.png" as CFString, 1, nil)
    else { exit(3) }
    CGImageDestinationAddImage(dest, drawn, nil)
    guard CGImageDestinationFinalize(dest) else { exit(3) }
}
