// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//
// The bytes of the thumbnail.png IngeTrazo stores in an .igz when it saves
// it (formats/igz.py, views/document_thumbnail.py), for the macOS Quick Look
// thumbnail extension (ThumbnailProvider.swift).
//
// The same reading as the Windows handler (installer/thumbnail): ONE member
// of the ZIP container and never the model, through the end of central
// directory record, the central directory, the member's local header and
// its bytes. The picture is stored (not deflated). A plain-JSON document,
// or one saved without a picture, gives nil, and Finder shows the icon.
// The file comes from anywhere: every offset and size is checked against
// the file before it is used, and the picture may not exceed 8 MB.

import Foundation

enum IgzThumbnail {
    static let maxPicture: UInt64 = 8 << 20          // bytes
    static let maxCentral: UInt64 = 64 << 20         // bytes of central directory
    static let entry = Array("thumbnail.png".utf8)
    static let pngMagic: [UInt8] = [0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A]

    static let endSig: UInt32 = 0x0605_4b50
    static let zip64LocatorSig: UInt32 = 0x0706_4b50
    static let zip64EndSig: UInt32 = 0x0606_4b50
    static let centralSig: UInt32 = 0x0201_4b50
    static let localSig: UInt32 = 0x0403_4b50

    /// The PNG bytes of the document's picture, or nil.
    static func png(at url: URL) -> Data? {
        guard let file = try? FileHandle(forReadingFrom: url) else { return nil }
        defer { try? file.close() }
        guard let size = try? file.seekToEnd() else { return nil }
        return read(file, size: size)
    }

    // Exactly n bytes at offset off, or nil.
    private static func readAt(_ f: FileHandle, _ off: UInt64, _ n: Int) -> [UInt8]? {
        if n == 0 { return [] }
        guard (try? f.seek(toOffset: off)) != nil,
              let d = try? f.read(upToCount: n), d.count == n else { return nil }
        return [UInt8](d)
    }

    private static func u16(_ b: [UInt8], _ i: Int) -> UInt64 {
        UInt64(b[i]) | UInt64(b[i + 1]) << 8
    }

    private static func u32(_ b: [UInt8], _ i: Int) -> UInt64 {
        u16(b, i) | u16(b, i + 2) << 16
    }

    private static func u64(_ b: [UInt8], _ i: Int) -> UInt64 {
        u32(b, i) | u32(b, i + 4) << 32
    }

    private static func read(_ f: FileHandle, size: UInt64) -> Data? {
        if size < 22 { return nil }
        // The end record sits in the last 22 bytes plus a comment of up to 64 KB.
        let tail = Int(min(size, 22 + 0xFFFF))
        guard let end = readAt(f, size - UInt64(tail), tail) else { return nil }
        var found = -1
        var i = tail - 22
        while i >= 0 {
            if u32(end, i) == UInt64(endSig) && i + 22 + Int(u16(end, i + 20)) <= tail {
                found = i
                break
            }
            i -= 1
        }
        if found < 0 { return nil }                  // not a ZIP: a plain document
        let endAt = size - UInt64(tail) + UInt64(found)
        var entries = u16(end, found + 10)
        var cdSize = u32(end, found + 12)
        var cdOff = u32(end, found + 16)

        if entries == 0xFFFF || cdSize == 0xFFFF_FFFF || cdOff == 0xFFFF_FFFF {
            // ZIP64 (a document over 4 GB): the locator just before the end
            // record points at the ZIP64 end record, which holds the real values.
            if endAt < 20 { return nil }
            guard let loc = readAt(f, endAt - 20, 20), u32(loc, 0) == UInt64(zip64LocatorSig)
            else { return nil }
            let z64 = u64(loc, 8)
            if z64 > size || size - z64 < 56 { return nil }
            guard let rec = readAt(f, z64, 56), u32(rec, 0) == UInt64(zip64EndSig)
            else { return nil }
            entries = u64(rec, 32)
            cdSize = u64(rec, 40)
            cdOff = u64(rec, 48)
        }
        if cdOff > size || cdSize > size - cdOff || cdSize > maxCentral { return nil }
        guard let cd = readAt(f, cdOff, Int(cdSize)) else { return nil }

        var at = 0
        var k: UInt64 = 0
        while k < entries {
            if cd.count - at < 46 || u32(cd, at) != UInt64(centralSig) { return nil }
            let method = u16(cd, at + 10)
            var packed = u32(cd, at + 20)
            var plain = u32(cd, at + 24)
            let n = Int(u16(cd, at + 28))
            let x = Int(u16(cd, at + 30))
            let c = Int(u16(cd, at + 32))
            var local = u32(cd, at + 42)
            let whole = 46 + n + x + c
            if cd.count - at < whole { return nil }
            if n == entry.count && Array(cd[(at + 46)..<(at + 46 + n)]) == entry {
                // Values too big for 32 bits are in the ZIP64 extra field, in
                // this order, each only when its 32-bit field says so.
                let ex = at + 46 + n
                var j = 0
                while j + 4 <= x {
                    let id = u16(cd, ex + j)
                    let len = Int(u16(cd, ex + j + 2))
                    if j + 4 + len > x { break }
                    if id == 0x0001 {
                        var p = ex + j + 4
                        var left = len
                        if plain == 0xFFFF_FFFF && left >= 8 { plain = u64(cd, p); p += 8; left -= 8 }
                        if packed == 0xFFFF_FFFF && left >= 8 { packed = u64(cd, p); p += 8; left -= 8 }
                        if local == 0xFFFF_FFFF && left >= 8 { local = u64(cd, p) }
                        break
                    }
                    j += 4 + len
                }
                // Stored only: IngeTrazo never deflates the picture.
                if method != 0 || packed != plain || plain < UInt64(pngMagic.count)
                    || plain > maxPicture { return nil }
                if local > size || size - local < 30 { return nil }
                guard let lh = readAt(f, local, 30), u32(lh, 0) == UInt64(localSig)
                else { return nil }
                let data = local + 30 + u16(lh, 26) + u16(lh, 28)
                if data > size || plain > size - data { return nil }
                guard let out = readAt(f, data, Int(plain)),
                      Array(out.prefix(pngMagic.count)) == pngMagic else { return nil }
                return Data(out)
            }
            at += whole
            k += 1
        }
        return nil                                   // saved without a picture
    }
}
