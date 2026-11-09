// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! Replays a recorded sequence of OpenGL calls — the viewport's instanced
//! passes, recorded call for call by `views.viewport._GlTape` — through the
//! driver's own entry points (taken from the current Qt context), so a frame
//! of a few thousand draws costs no Python. The calls and their order are
//! exactly the recorded ones; the caller makes sure the context is current
//! and the same program is bound.

pub const DRAW_ARRAYS_INSTANCED: i64 = 0;
pub const BIND_VERTEX_ARRAY: i64 = 1;
pub const UNIFORM_1I: i64 = 2;
pub const UNIFORM_1F: i64 = 3;
pub const UNIFORM_4F: i64 = 4;
pub const ENABLE: i64 = 5;
pub const DISABLE: i64 = 6;
pub const CULL_FACE: i64 = 7;
pub const FRONT_FACE: i64 = 8;
pub const ACTIVE_TEXTURE: i64 = 9;
pub const BIND_TEXTURE: i64 = 10;
pub const STENCIL_FUNC: i64 = 11;
pub const N_FUNCS: usize = 12;

type FnDrawArraysInstanced = extern "system" fn(u32, i32, i32, i32);
type FnU32 = extern "system" fn(u32);
type FnUniform1i = extern "system" fn(i32, i32);
type FnUniform1f = extern "system" fn(i32, f32);
type FnUniform4f = extern "system" fn(i32, f32, f32, f32, f32);
type FnBindTexture = extern "system" fn(u32, u32);
type FnStencilFunc = extern "system" fn(u32, i32, u32);

pub struct Tape {
    f: [usize; N_FUNCS],
}

impl Tape {
    /// `addrs`: the entry points, in opcode order; none may be null.
    pub fn new(addrs: &[usize]) -> Option<Tape> {
        if addrs.len() != N_FUNCS || addrs.iter().any(|&a| a == 0) {
            return None;
        }
        let mut f = [0usize; N_FUNCS];
        f.copy_from_slice(addrs);
        Some(Tape { f })
    }

    /// Run `ops` (rows of `[opcode, a, b, c, d]`) with `vals` (rows of four
    /// floats, the float arguments). Returns the number of calls made, or
    /// the row of the first unknown opcode as an error.
    ///
    /// # Safety
    /// The entry points must belong to the GL context current on this
    /// thread, and the arguments must be what those calls accept.
    pub unsafe fn run(&self, ops: &[[i64; 5]], vals: &[[f32; 4]]) -> Result<usize, usize> {
        let f = &self.f;
        for (r, op) in ops.iter().enumerate() {
            let v = vals[r];
            match op[0] {
                DRAW_ARRAYS_INSTANCED => {
                    let g: FnDrawArraysInstanced = std::mem::transmute(f[0]);
                    g(op[1] as u32, op[2] as i32, op[3] as i32, op[4] as i32)
                }
                BIND_VERTEX_ARRAY => {
                    let g: FnU32 = std::mem::transmute(f[1]);
                    g(op[1] as u32)
                }
                UNIFORM_1I => {
                    let g: FnUniform1i = std::mem::transmute(f[2]);
                    g(op[1] as i32, op[2] as i32)
                }
                UNIFORM_1F => {
                    let g: FnUniform1f = std::mem::transmute(f[3]);
                    g(op[1] as i32, v[0])
                }
                UNIFORM_4F => {
                    let g: FnUniform4f = std::mem::transmute(f[4]);
                    g(op[1] as i32, v[0], v[1], v[2], v[3])
                }
                ENABLE | DISABLE | CULL_FACE | FRONT_FACE | ACTIVE_TEXTURE => {
                    let g: FnU32 = std::mem::transmute(f[op[0] as usize]);
                    g(op[1] as u32)
                }
                BIND_TEXTURE => {
                    let g: FnBindTexture = std::mem::transmute(f[10]);
                    g(op[1] as u32, op[2] as u32)
                }
                STENCIL_FUNC => {
                    let g: FnStencilFunc = std::mem::transmute(f[11]);
                    g(op[1] as u32, op[2] as i32, op[3] as u32)
                }
                _ => return Err(r),
            }
        }
        Ok(ops.len())
    }
}
