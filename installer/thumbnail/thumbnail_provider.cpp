// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//
// The picture of an .igz in the Windows file manager and in the open and
// save dialogs: a shell thumbnail handler (IThumbnailProvider, initialised
// with a stream) that hands Windows the thumbnail.png IngeTrazo stores in
// the document when it saves it (formats/igz.py, views/document_thumbnail.py).
//
// - It reads ONE member of the ZIP container and never the model: the end
//   of central directory record, the central directory, the member's local
//   header and its bytes. The picture is stored (not deflated), so no
//   inflater is needed. A plain-JSON document, or one saved without a
//   picture, gets no thumbnail and Windows shows the document icon.
// - The file comes from anywhere, so every offset and size is checked
//   against the stream before it is used, the picture may not exceed 8 MB
//   or 4096 px a side, and only the PNG decoder of the Windows Imaging
//   Component reads it.
// - Explorer runs it in a separate host process (dllhost.exe), so a
//   failure here never takes the file manager down with it.
//
// Built by build.cmd (MSVC, static runtime: the host process does not see
// the libraries inside the IngeTrazo folder). Registered by the installer
// (installer/ingetrazo.iss) under the IngeTrazo.Document ProgID.

#include <windows.h>
#include <shlwapi.h>
#include <thumbcache.h>
#include <wincodec.h>

#include <cstdint>
#include <cstring>
#include <new>
#include <vector>

#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "shlwapi.lib")
#pragma comment(lib, "ole32.lib")
#pragma comment(lib, "windowscodecs.lib")

// {78547A98-072B-4C96-98A2-EFE80F7C48FA} — never change it: the installer
// registers this CLSID, and an upgrade must find the same one.
static const CLSID CLSID_IgzThumbnailProvider = {
    0x78547a98, 0x072b, 0x4c96, {0x98, 0xa2, 0xef, 0xe8, 0x0f, 0x7c, 0x48, 0xfa}};

static long g_objects = 0;
static long g_locks = 0;

namespace igz {

constexpr uint32_t kEndSig = 0x06054b50;        // end of central directory
constexpr uint32_t kZip64LocatorSig = 0x07064b50;
constexpr uint32_t kZip64EndSig = 0x06064b50;
constexpr uint32_t kCentralSig = 0x02014b50;
constexpr uint32_t kLocalSig = 0x04034b50;
constexpr uint32_t kMaxPicture = 8u << 20;      // bytes
constexpr uint64_t kMaxCentral = 64ull << 20;   // bytes of central directory
constexpr UINT kMaxSide = 4096;                 // pixels
const char kEntry[] = "thumbnail.png";
const BYTE kPngMagic[8] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};

inline uint16_t Rd16(const BYTE* p) { return uint16_t(p[0] | (p[1] << 8)); }
inline uint32_t Rd32(const BYTE* p) {
    return uint32_t(p[0]) | (uint32_t(p[1]) << 8) | (uint32_t(p[2]) << 16) |
           (uint32_t(p[3]) << 24);
}
inline uint64_t Rd64(const BYTE* p) { return Rd32(p) | (uint64_t(Rd32(p + 4)) << 32); }

// Exactly n bytes at offset off, or a failure.
HRESULT ReadAt(IStream* s, uint64_t off, void* buf, ULONG n) {
    LARGE_INTEGER at;
    at.QuadPart = static_cast<LONGLONG>(off);
    HRESULT hr = s->Seek(at, STREAM_SEEK_SET, nullptr);
    if (FAILED(hr)) return hr;
    BYTE* p = static_cast<BYTE*>(buf);
    while (n) {
        ULONG got = 0;
        hr = s->Read(p, n, &got);
        if (FAILED(hr)) return hr;
        if (got == 0) return E_FAIL;            // the stream ended early
        p += got;
        n -= got;
    }
    return S_OK;
}

// The bytes of thumbnail.png, stored in the ZIP held by the stream.
HRESULT ReadPicture(IStream* s, std::vector<BYTE>& out) {
    STATSTG st = {};
    HRESULT hr = s->Stat(&st, STATFLAG_NONAME);
    if (FAILED(hr)) return hr;
    const uint64_t size = st.cbSize.QuadPart;
    if (size < 22) return E_FAIL;

    // The end record sits in the last 22 bytes plus a comment of up to 64 KB.
    const ULONG tail = static_cast<ULONG>(size < 22 + 0xFFFF ? size : 22 + 0xFFFF);
    std::vector<BYTE> end(tail);
    hr = ReadAt(s, size - tail, end.data(), tail);
    if (FAILED(hr)) return hr;
    long found = -1;
    for (long i = long(tail) - 22; i >= 0; --i) {
        if (Rd32(&end[i]) == kEndSig &&
            uint64_t(i) + 22 + Rd16(&end[i + 20]) <= tail) {
            found = i;
            break;
        }
    }
    if (found < 0) return E_FAIL;               // not a ZIP: a plain document
    const BYTE* e = &end[found];
    const uint64_t endAt = size - tail + uint64_t(found);
    uint64_t entries = Rd16(e + 10);
    uint64_t cdSize = Rd32(e + 12);
    uint64_t cdOff = Rd32(e + 16);

    if (entries == 0xFFFF || cdSize == 0xFFFFFFFF || cdOff == 0xFFFFFFFF) {
        // ZIP64 (a document over 4 GB): the locator just before the end
        // record points at the ZIP64 end record, which holds the real values.
        if (endAt < 20) return E_FAIL;
        BYTE loc[20];
        hr = ReadAt(s, endAt - 20, loc, sizeof loc);
        if (FAILED(hr) || Rd32(loc) != kZip64LocatorSig) return E_FAIL;
        const uint64_t z64 = Rd64(loc + 8);
        if (z64 > size || size - z64 < 56) return E_FAIL;
        BYTE rec[56];
        hr = ReadAt(s, z64, rec, sizeof rec);
        if (FAILED(hr) || Rd32(rec) != kZip64EndSig) return E_FAIL;
        entries = Rd64(rec + 32);
        cdSize = Rd64(rec + 40);
        cdOff = Rd64(rec + 48);
    }
    if (cdOff > size || cdSize > size - cdOff || cdSize > kMaxCentral) return E_FAIL;

    std::vector<BYTE> cd(static_cast<size_t>(cdSize));
    if (cdSize) {
        hr = ReadAt(s, cdOff, cd.data(), static_cast<ULONG>(cdSize));
        if (FAILED(hr)) return hr;
    }
    const size_t nameLen = sizeof kEntry - 1;
    size_t at = 0;
    for (uint64_t k = 0; k < entries; ++k) {
        if (cd.size() - at < 46 || Rd32(&cd[at]) != kCentralSig) return E_FAIL;
        const BYTE* h = &cd[at];
        const uint16_t method = Rd16(h + 10);
        uint64_t packed = Rd32(h + 20);
        uint64_t plain = Rd32(h + 24);
        const uint16_t n = Rd16(h + 28);
        const uint16_t x = Rd16(h + 30);
        const uint16_t c = Rd16(h + 32);
        uint64_t local = Rd32(h + 42);
        const size_t whole = size_t(46) + n + x + c;
        if (cd.size() - at < whole) return E_FAIL;
        if (n == nameLen && std::memcmp(h + 46, kEntry, nameLen) == 0) {
            // Values too big for 32 bits are in the ZIP64 extra field, in
            // this order, each only when its 32-bit field says so.
            const BYTE* ex = h + 46 + n;
            for (size_t i = 0; i + 4 <= x;) {
                const uint16_t id = Rd16(ex + i);
                const uint16_t len = Rd16(ex + i + 2);
                if (i + 4 + len > x) break;
                if (id == 0x0001) {
                    const BYTE* f = ex + i + 4;
                    size_t left = len;
                    if (plain == 0xFFFFFFFF && left >= 8) { plain = Rd64(f); f += 8; left -= 8; }
                    if (packed == 0xFFFFFFFF && left >= 8) { packed = Rd64(f); f += 8; left -= 8; }
                    if (local == 0xFFFFFFFF && left >= 8) { local = Rd64(f); }
                    break;
                }
                i += 4 + size_t(len);
            }
            // Stored only: IngeTrazo never deflates the picture.
            if (method != 0 || packed != plain || plain < sizeof kPngMagic ||
                plain > kMaxPicture)
                return E_FAIL;
            BYTE lh[30];
            if (local > size || size - local < sizeof lh) return E_FAIL;
            hr = ReadAt(s, local, lh, sizeof lh);
            if (FAILED(hr) || Rd32(lh) != kLocalSig) return E_FAIL;
            const uint64_t data = local + 30 + Rd16(lh + 26) + Rd16(lh + 28);
            if (data > size || plain > size - data) return E_FAIL;
            out.resize(static_cast<size_t>(plain));
            hr = ReadAt(s, data, out.data(), static_cast<ULONG>(plain));
            if (FAILED(hr)) return hr;
            if (std::memcmp(out.data(), kPngMagic, sizeof kPngMagic) != 0) return E_FAIL;
            return S_OK;
        }
        at += whole;
    }
    return E_FAIL;                              // saved without a picture
}

// The PNG decoded and fitted inside cx × cx (never enlarged), as a
// top-down 32-bit DIB section.
HRESULT Decode(const std::vector<BYTE>& png, UINT cx, HBITMAP* bitmap) {
    IWICImagingFactory* factory = nullptr;
    IWICStream* stream = nullptr;
    IWICBitmapDecoder* decoder = nullptr;
    IWICBitmapFrameDecode* frame = nullptr;
    IWICBitmapScaler* scaler = nullptr;
    IWICFormatConverter* converter = nullptr;
    HRESULT hr = CoCreateInstance(CLSID_WICImagingFactory, nullptr,
                                  CLSCTX_INPROC_SERVER, IID_PPV_ARGS(&factory));
    if (SUCCEEDED(hr)) hr = factory->CreateStream(&stream);
    if (SUCCEEDED(hr))
        hr = stream->InitializeFromMemory(const_cast<BYTE*>(png.data()),
                                          static_cast<DWORD>(png.size()));
    // The PNG decoder and no other: the bytes are not trusted.
    if (SUCCEEDED(hr)) hr = factory->CreateDecoder(GUID_ContainerFormatPng, nullptr, &decoder);
    if (SUCCEEDED(hr)) hr = decoder->Initialize(stream, WICDecodeMetadataCacheOnDemand);
    if (SUCCEEDED(hr)) hr = decoder->GetFrame(0, &frame);
    UINT w = 0, h = 0;
    if (SUCCEEDED(hr)) hr = frame->GetSize(&w, &h);
    if (SUCCEEDED(hr) && (w == 0 || h == 0 || w > kMaxSide || h > kMaxSide)) hr = E_FAIL;
    UINT tw = w, th = h;
    if (SUCCEEDED(hr) && cx > 0 && (w > cx || h > cx)) {
        if (w >= h) {
            tw = cx;
            th = UINT((uint64_t(h) * cx + w / 2) / w);
        } else {
            th = cx;
            tw = UINT((uint64_t(w) * cx + h / 2) / h);
        }
        if (tw == 0) tw = 1;
        if (th == 0) th = 1;
    }
    IWICBitmapSource* source = frame;
    if (SUCCEEDED(hr) && (tw != w || th != h)) {
        hr = factory->CreateBitmapScaler(&scaler);
        if (SUCCEEDED(hr)) hr = scaler->Initialize(frame, tw, th, WICBitmapInterpolationModeFant);
        if (SUCCEEDED(hr)) source = scaler;
    }
    if (SUCCEEDED(hr)) hr = factory->CreateFormatConverter(&converter);
    if (SUCCEEDED(hr))
        hr = converter->Initialize(source, GUID_WICPixelFormat32bppBGRA,
                                   WICBitmapDitherTypeNone, nullptr, 0.0,
                                   WICBitmapPaletteTypeCustom);
    if (SUCCEEDED(hr)) {
        BITMAPINFO bmi = {};
        bmi.bmiHeader.biSize = sizeof bmi.bmiHeader;
        bmi.bmiHeader.biWidth = LONG(tw);
        bmi.bmiHeader.biHeight = -LONG(th);     // top-down
        bmi.bmiHeader.biPlanes = 1;
        bmi.bmiHeader.biBitCount = 32;
        bmi.bmiHeader.biCompression = BI_RGB;
        void* bits = nullptr;
        HBITMAP dib = CreateDIBSection(nullptr, &bmi, DIB_RGB_COLORS, &bits, nullptr, 0);
        hr = dib ? S_OK : E_OUTOFMEMORY;
        if (SUCCEEDED(hr)) {
            const UINT stride = tw * 4;
            hr = converter->CopyPixels(nullptr, stride, stride * th, static_cast<BYTE*>(bits));
            if (SUCCEEDED(hr))
                *bitmap = dib;
            else
                DeleteObject(dib);
        }
    }
    if (converter) converter->Release();
    if (scaler) scaler->Release();
    if (frame) frame->Release();
    if (decoder) decoder->Release();
    if (stream) stream->Release();
    if (factory) factory->Release();
    return hr;
}

}  // namespace igz

class ThumbnailProvider final : public IInitializeWithStream, public IThumbnailProvider {
public:
    ThumbnailProvider() { InterlockedIncrement(&g_objects); }

    // IUnknown
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        static const QITAB table[] = {
            QITABENT(ThumbnailProvider, IInitializeWithStream),
            QITABENT(ThumbnailProvider, IThumbnailProvider),
            {nullptr, 0},
        };
        return QISearch(this, table, riid, ppv);
    }
    IFACEMETHODIMP_(ULONG) AddRef() override { return InterlockedIncrement(&refs_); }
    IFACEMETHODIMP_(ULONG) Release() override {
        const long left = InterlockedDecrement(&refs_);
        if (left == 0) delete this;
        return ULONG(left);
    }

    // IInitializeWithStream
    IFACEMETHODIMP Initialize(IStream* stream, DWORD) override {
        if (!stream) return E_INVALIDARG;
        if (stream_) return HRESULT_FROM_WIN32(ERROR_ALREADY_INITIALIZED);
        return stream->QueryInterface(IID_PPV_ARGS(&stream_));
    }

    // IThumbnailProvider
    IFACEMETHODIMP GetThumbnail(UINT cx, HBITMAP* bitmap, WTS_ALPHATYPE* alpha) override {
        if (!bitmap || !alpha) return E_POINTER;
        *bitmap = nullptr;
        *alpha = WTSAT_UNKNOWN;
        if (!stream_) return E_UNEXPECTED;
        std::vector<BYTE> png;
        HRESULT hr = igz::ReadPicture(stream_, png);
        if (SUCCEEDED(hr)) hr = igz::Decode(png, cx, bitmap);
        if (SUCCEEDED(hr)) *alpha = WTSAT_ARGB;
        return hr;
    }

private:
    ~ThumbnailProvider() {
        if (stream_) stream_->Release();
        InterlockedDecrement(&g_objects);
    }
    long refs_ = 1;
    IStream* stream_ = nullptr;
};

class ClassFactory final : public IClassFactory {
public:
    IFACEMETHODIMP QueryInterface(REFIID riid, void** ppv) override {
        static const QITAB table[] = {
            QITABENT(ClassFactory, IClassFactory),
            {nullptr, 0},
        };
        return QISearch(this, table, riid, ppv);
    }
    IFACEMETHODIMP_(ULONG) AddRef() override { return 2; }   // static object
    IFACEMETHODIMP_(ULONG) Release() override { return 1; }

    IFACEMETHODIMP CreateInstance(IUnknown* outer, REFIID riid, void** ppv) override {
        if (!ppv) return E_POINTER;
        *ppv = nullptr;
        if (outer) return CLASS_E_NOAGGREGATION;
        ThumbnailProvider* p = new (std::nothrow) ThumbnailProvider();
        if (!p) return E_OUTOFMEMORY;
        const HRESULT hr = p->QueryInterface(riid, ppv);
        p->Release();
        return hr;
    }
    IFACEMETHODIMP LockServer(BOOL lock) override {
        if (lock)
            InterlockedIncrement(&g_locks);
        else
            InterlockedDecrement(&g_locks);
        return S_OK;
    }
};

static ClassFactory g_factory;

STDAPI DllGetClassObject(REFCLSID clsid, REFIID riid, void** ppv) {
    if (!ppv) return E_POINTER;
    *ppv = nullptr;
    if (!IsEqualCLSID(clsid, CLSID_IgzThumbnailProvider)) return CLASS_E_CLASSNOTAVAILABLE;
    return g_factory.QueryInterface(riid, ppv);
}

STDAPI DllCanUnloadNow() {
    return (g_objects == 0 && g_locks == 0) ? S_OK : S_FALSE;
}

BOOL APIENTRY DllMain(HINSTANCE module, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_ATTACH) DisableThreadLibraryCalls(module);
    return TRUE;
}
