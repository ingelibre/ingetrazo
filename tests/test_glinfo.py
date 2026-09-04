# SPDX-License-Identifier: GPL-3.0-or-later
"""Who draws the viewport — the diagnosis behind "IngeTrazo is unusably
slow on my Windows machine"."""
from __future__ import annotations

from core.glinfo import (GL_RENDERER, GL_VENDOR, GL_VERSION, describe,
                         is_software_renderer, read_gl_info, write_gl_report)


class _GL:
    def __init__(self, strings, fail=False):
        self.strings, self.fail = strings, fail

    def glGetString(self, enum):
        if self.fail:
            raise RuntimeError("no context")
        return self.strings.get(enum)


def test_software_rasterisers_are_recognised_and_gpus_are_not():
    assert is_software_renderer("GDI Generic", "Microsoft Corporation")
    assert is_software_renderer("llvmpipe (LLVM 17.0.6, 256 bits)", "Mesa")
    assert is_software_renderer("Google SwiftShader")
    assert not is_software_renderer("NVIDIA GeForce RTX 3060/PCIe/SSE2", "NVIDIA Corporation")
    assert not is_software_renderer("Intel(R) Iris(R) Xe Graphics", "Intel")
    assert not is_software_renderer("AMD Radeon RX 6600 (radeonsi, navi23)", "AMD")


def test_read_gl_info_decodes_bytes_and_flags_software():
    gl = _GL({GL_VENDOR: b"Microsoft Corporation", GL_RENDERER: b"GDI Generic",
              GL_VERSION: b"1.1.0"})
    info = read_gl_info(gl)
    assert info == {"vendor": "Microsoft Corporation", "renderer": "GDI Generic",
                    "version": "1.1.0", "software": True}
    gpu = read_gl_info(_GL({GL_VENDOR: "NVIDIA Corporation",
                            GL_RENDERER: "NVIDIA GeForce GTX 1650/PCIe/SSE2",
                            GL_VERSION: "3.3.0 NVIDIA 552.44"}))
    assert gpu["software"] is False
    assert describe(gpu) == ("NVIDIA GeForce GTX 1650/PCIe/SSE2 (NVIDIA Corporation) "
                             "— OpenGL 3.3.0 NVIDIA 552.44")


def test_a_silent_driver_never_breaks_start_up():
    info = read_gl_info(_GL({}, fail=True))
    assert info == {"vendor": "", "renderer": "", "version": "", "software": False}
    assert describe(info) == ""


def test_the_report_lands_in_the_log_folder(tmp_path):
    info = {"vendor": "Intel", "renderer": "Intel(R) UHD Graphics 620",
            "version": "4.6.0 - Build 31.0.101.2111", "software": False}
    out = write_gl_report(info, tmp_path / "logs" / "ingetrazo-gl.txt")
    text = out.read_text(encoding="utf-8")
    assert "renderer : Intel(R) UHD Graphics 620" in text
    assert "software : no" in text
