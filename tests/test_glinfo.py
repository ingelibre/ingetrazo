# SPDX-License-Identifier: GPL-3.0-or-later
"""Who draws the viewport — the diagnosis behind "IngeTrazo is unusably
slow on my Windows machine"."""
from __future__ import annotations

from core.glinfo import (GL_RENDERER, GL_VENDOR, GL_VERSION, describe,
                         is_software_renderer, meets_gl_requirement,
                         parse_gl_version, read_gl_info, write_gl_report)


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


def test_the_version_number_is_read_from_the_vendor_text():
    assert parse_gl_version("3.0 Mesa 11.2.2") == (3, 0)
    assert parse_gl_version("4.6.0 NVIDIA 552.44") == (4, 6)
    assert parse_gl_version("3.3 (Core Profile) Mesa 24.0.5") == (3, 3)
    assert parse_gl_version("4.6.0 - Build 31.0.101.2111") == (4, 6)
    assert parse_gl_version("1.1.0") == (1, 1)
    assert parse_gl_version("") is None
    assert parse_gl_version("unknown") is None


def test_only_desktop_gl_3_3_or_newer_can_compile_the_shaders():
    # Issue #751: Qt fell back to opengl32sw.dll, whose llvmpipe gave a
    # 3.0 context, and every #version 330 core shader failed.
    assert not meets_gl_requirement("3.0 Mesa 11.2.2")
    assert not meets_gl_requirement("2.1 Mesa 23.2.1")
    assert not meets_gl_requirement("1.1.0")             # GDI Generic
    assert not meets_gl_requirement("3.2.0 NVIDIA 340.108")
    assert meets_gl_requirement("3.3.0 NVIDIA 552.44")
    assert meets_gl_requirement("4.6.0 NVIDIA 552.44")
    assert meets_gl_requirement("4.1 INTEL-20.5.17")
    assert meets_gl_requirement("10.0 Future 1.0")
    # GLSL ES cannot take a desktop #version 330 core shader at any version.
    assert not meets_gl_requirement("OpenGL ES 3.2 Mesa 24.0.5")
    assert not meets_gl_requirement("OpenGL ES 3.0 (ANGLE 2.1.0)")


def test_an_unreadable_version_is_left_to_the_shader_compiler():
    # read_gl_info yields "" when the driver answers nothing; refusing then
    # would block a working machine on a missing string.
    assert meets_gl_requirement("")
