// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! A JSON document's mesh blocks as arrays (`formats.igz._parse_native`).
//!
//! An old document spells every coordinate of every mesh in JSON, and the
//! interpreter's parser turned 3.3 GB of it into a tree of 8.8 GB for
//! `_json_arrays` to flatten and drop (#158). Here the `"edges"` and
//! `"faces"` of every mesh block go straight to those arrays; the rest of the
//! document — what is left is small — stays text, for `json.loads`.
//!
//! Only what `_json_arrays` reads the same way is taken: a mesh block in
//! the places the loader looks for one, numbers json.loads would read, flags
//! that are `true`/`false`. Anything else, malformed or merely unusual, is a
//! [`Bail`]: the caller reads the whole document the old way, so a document
//! never opens differently (or fails differently) because of this file.

use rayon::prelude::*;
use std::collections::HashMap;

/// Something this reader does not take; the old parser decides.
#[derive(Debug)]
pub struct Bail;
type R<T> = Result<T, Bail>;

const MAX_DEPTH: usize = 32;

#[derive(Clone, Copy, PartialEq)]
enum Kind {
    Scene,
    Proto,
    Group,
}

struct Span {
    edges: Option<(usize, usize)>,
    faces: Option<(usize, usize)>,
}

/// One mesh block, in `_json_arrays`'s order: the two ends of every edge,
/// then each face's ring and its holes.
#[derive(Default)]
pub struct Block {
    pub pos: Vec<f64>,
    pub flags: Vec<u8>,
    pub curves: Vec<i64>,
    pub layers: Vec<i32>,
    /// Layer names as they are spelled in the document, quotes included.
    pub layer_names: Vec<Vec<u8>>,
    pub sizes: Vec<i64>,
    pub counts: Vec<i64>,
    pub face_attr: Vec<i64>,
    /// Each distinct set of a face's other members, as a JSON object's text.
    pub attrs: Vec<Vec<u8>>,
    /// The faces with more than one hole (`_maximal_holes` is Python's).
    pub multi: Vec<i64>,
}

#[inline]
fn ws(d: &[u8], mut i: usize) -> usize {
    while i < d.len() && matches!(d[i], b' ' | b'\n' | b'\r' | b'\t') {
        i += 1;
    }
    i
}

#[inline]
fn at(d: &[u8], i: usize) -> R<u8> {
    d.get(i).copied().ok_or(Bail)
}

#[inline]
fn expect(d: &[u8], i: usize, c: u8) -> R<usize> {
    if at(d, i)? == c {
        Ok(i + 1)
    } else {
        Err(Bail)
    }
}

/// Past the string opening at `i`.
#[inline]
fn skip_string(d: &[u8], mut i: usize) -> R<usize> {
    i += 1;
    loop {
        match at(d, i)? {
            b'"' => return Ok(i + 1),
            b'\\' => i += 2,
            _ => i += 1,
        }
    }
}

/// The first byte at or after `i` that is a quote or a bracket, eight at a
/// time: an old document is mostly spaces and digits between them.
#[inline]
fn next_structural(d: &[u8], mut i: usize) -> usize {
    const L: u64 = 0x0101_0101_0101_0101;
    const H: u64 = 0x8080_8080_8080_8080;
    #[inline]
    fn zero(x: u64) -> u64 {
        x.wrapping_sub(L) & !x & H
    }
    while let Some(c) = d.get(i..i + 8) {
        let w = u64::from_le_bytes(c.try_into().unwrap());
        let b = w | (L * 0x20); // [ ] to { }
        let m = zero(w ^ (L * b'"' as u64)) | zero(b ^ (L * b'{' as u64)) | zero(b ^ (L * b'}' as u64));
        if m != 0 {
            return i + (m.trailing_zeros() / 8) as usize;
        }
        i += 8;
    }
    i
}

/// Past the value at `i`, only matching its brackets: what is copied is
/// checked by the parser that reads it later, what is parsed here is checked
/// here.
fn skip_value(d: &[u8], mut i: usize) -> R<usize> {
    match at(d, i)? {
        b'"' => skip_string(d, i),
        b'[' | b'{' => {
            let mut depth = 0usize;
            loop {
                i = next_structural(d, i);
                match at(d, i)? {
                    b'"' => {
                        i = skip_string(d, i)?;
                        continue;
                    }
                    b'[' | b'{' => depth += 1,
                    b']' | b'}' => {
                        depth -= 1;
                        if depth == 0 {
                            return Ok(i + 1);
                        }
                    }
                    _ => {}
                }
                i += 1;
            }
        }
        _ => {
            let s = i;
            while i < d.len() && !matches!(d[i], b',' | b']' | b'}' | b' ' | b'\n' | b'\r' | b'\t') {
                i += 1;
            }
            if i == s {
                Err(Bail)
            } else {
                Ok(i)
            }
        }
    }
}

/// The key at `i` (quotes included, no escapes taken) and where its value
/// starts.
#[inline]
fn key_at(d: &[u8], i: usize) -> R<(&[u8], usize)> {
    if at(d, i)? != b'"' {
        return Err(Bail);
    }
    let e = skip_string(d, i)?;
    let key = &d[i..e];
    if key.contains(&b'\\') {
        return Err(Bail);
    }
    let v = ws(d, expect(d, ws(d, e), b':')?);
    Ok((key, v))
}

struct Walker<'a> {
    d: &'a [u8],
    spans: Vec<Span>,
    /// `(start, end, block)`, in byte order: the array to take out of the
    /// text, and the block number to leave beside the first of each block.
    edits: Vec<(usize, usize, Option<usize>)>,
}

impl Walker<'_> {
    /// The object at `i`: a mesh block of `kind`. Returns where it ends.
    fn block(&mut self, mut i: usize, kind: Kind, depth: usize) -> R<usize> {
        if depth > MAX_DEPTH {
            return Err(Bail);
        }
        let d = self.d;
        let mut this: Option<usize> = None;
        let (mut seen_e, mut seen_f) = (false, false);
        i = ws(d, i + 1);
        if at(d, i)? == b'}' {
            return Ok(i + 1);
        }
        loop {
            let (key, v) = key_at(d, i)?;
            let end = match key {
                b"\"edges\"" | b"\"faces\"" => {
                    let is_e = key == b"\"edges\"";
                    if at(d, v)? != b'[' || (if is_e { seen_e } else { seen_f }) {
                        return Err(Bail);
                    }
                    if is_e {
                        seen_e = true;
                    } else {
                        seen_f = true;
                    }
                    let end = skip_value(d, v)?;
                    if ws(d, v + 1) != end - 1 {
                        let first = this.is_none();
                        let n = *this.get_or_insert_with(|| {
                            self.spans.push(Span { edges: None, faces: None });
                            self.spans.len() - 1
                        });
                        if is_e {
                            self.spans[n].edges = Some((v, end));
                        } else {
                            self.spans[n].faces = Some((v, end));
                        }
                        self.edits.push((v, end, first.then_some(n)));
                    }
                    end
                }
                b"\"_njb\"" => return Err(Bail),
                b"\"protos\"" if kind == Kind::Scene => self.blocks(v, Kind::Proto, depth + 1)?,
                b"\"groups\"" | b"\"kept_components\"" if kind == Kind::Scene => {
                    self.blocks(v, Kind::Group, depth + 1)?
                }
                b"\"children\"" if kind == Kind::Group => self.blocks(v, Kind::Group, depth + 1)?,
                _ => skip_value(d, v)?,
            };
            i = ws(d, end);
            match at(d, i)? {
                b',' => i = ws(d, i + 1),
                b'}' => return Ok(i + 1),
                _ => return Err(Bail),
            }
        }
    }

    /// A list of mesh blocks at `i`; anything else there is left alone.
    fn blocks(&mut self, mut i: usize, kind: Kind, depth: usize) -> R<usize> {
        let d = self.d;
        if at(d, i)? != b'[' {
            return skip_value(d, i);
        }
        i = ws(d, i + 1);
        if at(d, i)? == b']' {
            return Ok(i + 1);
        }
        loop {
            let end = if at(d, i)? == b'{' {
                self.block(i, kind, depth)?
            } else {
                skip_value(d, i)?
            };
            i = ws(d, end);
            match at(d, i)? {
                b',' => i = ws(d, i + 1),
                b']' => return Ok(i + 1),
                _ => return Err(Bail),
            }
        }
    }
}

/// A JSON number as json.loads reads it, for a coordinate: the grammar held
/// to, an integer's sign of zero dropped, nothing that would not be finite.
#[inline]
fn number(d: &[u8], s: usize) -> R<(f64, usize)> {
    let mut i = s;
    if at(d, i)? == b'-' {
        i += 1;
    }
    let digits = i;
    while i < d.len() && d[i].is_ascii_digit() {
        i += 1;
    }
    if i == digits || (d[digits] == b'0' && i - digits > 1) {
        return Err(Bail);
    }
    let mut integer = true;
    if i < d.len() && d[i] == b'.' {
        integer = false;
        i += 1;
        let f = i;
        while i < d.len() && d[i].is_ascii_digit() {
            i += 1;
        }
        if i == f {
            return Err(Bail);
        }
    }
    if i < d.len() && matches!(d[i], b'e' | b'E') {
        integer = false;
        i += 1;
        if i < d.len() && matches!(d[i], b'+' | b'-') {
            i += 1;
        }
        let f = i;
        while i < d.len() && d[i].is_ascii_digit() {
            i += 1;
        }
        if i == f {
            return Err(Bail);
        }
    }
    if integer && i - digits > 15 {
        return Err(Bail); // past what a double holds exactly
    }
    // SAFETY: only ASCII digits, sign, point and exponent were scanned.
    let text = unsafe { std::str::from_utf8_unchecked(&d[s..i]) };
    let v: f64 = text.parse().map_err(|_| Bail)?;
    if !v.is_finite() {
        return Err(Bail);
    }
    Ok((if integer && v == 0.0 { 0.0 } else { v }, i))
}

/// `[x, y, z]` at `i`, onto `out`.
#[inline]
fn point(d: &[u8], i: usize, out: &mut Vec<f64>) -> R<usize> {
    let mut i = ws(d, expect(d, i, b'[')?);
    for k in 0..3 {
        let (v, e) = number(d, i)?;
        out.push(v);
        i = ws(d, e);
        if k < 2 {
            i = ws(d, expect(d, i, b',')?);
        }
    }
    expect(d, i, b']')
}

/// A non-empty list of points at `i`, onto `out`; returns its end and size.
#[inline]
fn ring(d: &[u8], i: usize, out: &mut Vec<f64>) -> R<(usize, i64)> {
    let mut i = ws(d, expect(d, i, b'[')?);
    let mut n = 0;
    loop {
        i = ws(d, point(d, i, out)?);
        n += 1;
        match at(d, i)? {
            b',' => i = ws(d, i + 1),
            b']' => return Ok((i + 1, n)),
            _ => return Err(Bail),
        }
    }
}

/// `true` or `false` at `i`.
#[inline]
fn flag(d: &[u8], i: usize) -> R<(bool, usize)> {
    if d[i..].starts_with(b"true") {
        Ok((true, i + 4))
    } else if d[i..].starts_with(b"false") {
        Ok((false, i + 5))
    } else {
        Err(Bail)
    }
}

fn parse_edges(d: &[u8], s: usize, b: &mut Block, names: &mut HashMap<Vec<u8>, i32>) -> R<()> {
    let mut i = ws(d, s + 1);
    loop {
        i = ws(d, expect(d, i, b'{')?);
        let (mut pa, mut pb) = ([0.0f64; 3], [0.0f64; 3]);
        let mut seen = 0u8;
        let mut fl = 0u8;
        let (mut curve, mut layer) = (-1i64, -1i32);
        let mut buf: Vec<f64> = Vec::new();
        loop {
            let (key, v) = key_at(d, i)?;
            let bit;
            let end;
            match key {
                b"\"a\"" | b"\"b\"" => {
                    bit = if key == b"\"a\"" { 1 } else { 2 };
                    buf.clear();
                    end = point(d, v, &mut buf)?;
                    let p = [buf[0], buf[1], buf[2]];
                    if bit == 1 {
                        pa = p;
                    } else {
                        pb = p;
                    }
                }
                b"\"soft\"" | b"\"hidden\"" => {
                    bit = if key == b"\"soft\"" { 4 } else { 8 };
                    let (on, e) = flag(d, v)?;
                    if on {
                        fl |= if bit == 4 { 1 } else { 2 };
                    }
                    end = e;
                }
                b"\"curve\"" => {
                    bit = 16;
                    if d[v..].starts_with(b"null") {
                        end = v + 4;
                    } else {
                        let mut e = v;
                        while e < d.len() && d[e].is_ascii_digit() {
                            e += 1;
                        }
                        if e == v || e - v > 15 || (d[v] == b'0' && e - v > 1) {
                            return Err(Bail);
                        }
                        // SAFETY: ASCII digits only.
                        curve = unsafe { std::str::from_utf8_unchecked(&d[v..e]) }
                            .parse()
                            .map_err(|_| Bail)?;
                        end = e;
                    }
                }
                b"\"layer\"" => {
                    bit = 32;
                    if d[v..].starts_with(b"null") {
                        end = v + 4;
                    } else {
                        if at(d, v)? != b'"' {
                            return Err(Bail);
                        }
                        end = skip_string(d, v)?;
                        let name = &d[v..end];
                        layer = match names.get(name) {
                            Some(&n) => n,
                            None => {
                                let n = names.len() as i32;
                                names.insert(name.to_vec(), n);
                                b.layer_names.push(name.to_vec());
                                n
                            }
                        };
                    }
                }
                _ => return Err(Bail),
            }
            if seen & bit != 0 {
                return Err(Bail);
            }
            seen |= bit;
            i = ws(d, end);
            match at(d, i)? {
                b',' => i = ws(d, i + 1),
                b'}' => {
                    i += 1;
                    break;
                }
                _ => return Err(Bail),
            }
        }
        if seen & 3 != 3 {
            return Err(Bail);
        }
        b.pos.extend_from_slice(&pa);
        b.pos.extend_from_slice(&pb);
        b.flags.push(fl);
        b.curves.push(curve);
        b.layers.push(layer);
        i = ws(d, i);
        match at(d, i)? {
            b',' => i = ws(d, i + 1),
            b']' => return Ok(()),
            _ => return Err(Bail),
        }
    }
}

fn parse_faces(d: &[u8], s: usize, b: &mut Block) -> R<()> {
    let mut i = ws(d, s + 1);
    let mut table: HashMap<Vec<u8>, i64> = HashMap::new();
    let mut attrs: Vec<u8> = Vec::new();
    let mut holes: Vec<f64> = Vec::new();
    let mut hole_sizes: Vec<i64> = Vec::new();
    let mut face = 0i64;
    loop {
        i = ws(d, expect(d, i, b'{')?);
        attrs.clear();
        holes.clear();
        hole_sizes.clear();
        let mut verts: Option<i64> = None;
        let mut seen_holes = false;
        // The ring comes first in `pos` wherever "vertices" comes in the
        // object: it goes straight there, and a "holes" before it waits.
        loop {
            let (key, v) = key_at(d, i)?;
            let end;
            match key {
                b"\"vertices\"" => {
                    if verts.is_some() {
                        return Err(Bail);
                    }
                    let (e, n) = ring(d, v, &mut b.pos)?;
                    verts = Some(n);
                    end = e;
                }
                b"\"holes\"" => {
                    if seen_holes {
                        return Err(Bail);
                    }
                    seen_holes = true;
                    let mut j = ws(d, expect(d, v, b'[')?);
                    if at(d, j)? == b']' {
                        end = j + 1;
                    } else {
                        loop {
                            let (e, n) = ring(d, j, &mut holes)?;
                            hole_sizes.push(n);
                            j = ws(d, e);
                            match at(d, j)? {
                                b',' => j = ws(d, j + 1),
                                b']' => break,
                                _ => return Err(Bail),
                            }
                        }
                        end = j + 1;
                    }
                }
                _ => {
                    end = skip_value(d, v)?;
                    attrs.push(if attrs.is_empty() { b'{' } else { b',' });
                    attrs.extend_from_slice(key);
                    attrs.push(b':');
                    attrs.extend_from_slice(&d[v..end]);
                }
            }
            i = ws(d, end);
            match at(d, i)? {
                b',' => i = ws(d, i + 1),
                b'}' => {
                    i += 1;
                    break;
                }
                _ => return Err(Bail),
            }
        }
        b.sizes.push(verts.ok_or(Bail)?);
        b.sizes.extend_from_slice(&hole_sizes);
        b.pos.extend_from_slice(&holes);
        b.counts.push(1 + hole_sizes.len() as i64);
        if hole_sizes.len() > 1 {
            b.multi.push(face);
        }
        b.face_attr.push(if attrs.is_empty() {
            -1
        } else {
            attrs.push(b'}');
            match table.get(attrs.as_slice()) {
                Some(&k) => k,
                None => {
                    let k = b.attrs.len() as i64;
                    table.insert(attrs.clone(), k);
                    b.attrs.push(attrs.clone());
                    k
                }
            }
        });
        face += 1;
        i = ws(d, i);
        match at(d, i)? {
            b',' => i = ws(d, i + 1),
            b']' => return Ok(()),
            _ => return Err(Bail),
        }
    }
}

/// The document with every mesh block's arrays taken out (`"_njb": n` left
/// in each: its number in the second value), and those blocks.
pub fn mesh_blocks(d: &[u8]) -> R<(Vec<u8>, Vec<Block>)> {
    let mut w = Walker { d, spans: Vec::new(), edits: Vec::new() };
    let mut i = ws(d, 0);
    if at(d, i)? != b'{' {
        return Err(Bail);
    }
    i = ws(d, i + 1);
    if at(d, i)? != b'}' {
        loop {
            let (key, v) = key_at(d, i)?;
            let end = if key == b"\"scene\"" && at(d, v)? == b'{' {
                w.block(v, Kind::Scene, 0)?
            } else {
                skip_value(d, v)?
            };
            i = ws(d, end);
            match at(d, i)? {
                b',' => i = ws(d, i + 1),
                b'}' => break,
                _ => return Err(Bail),
            }
        }
    }
    if ws(d, i + 1) != d.len() {
        return Err(Bail);
    }
    let blocks = w
        .spans
        .par_iter()
        .map(|sp| {
            let mut b = Block::default();
            if let Some((s, _)) = sp.edges {
                let mut names = HashMap::new();
                parse_edges(d, s, &mut b, &mut names)?;
            }
            if let Some((s, _)) = sp.faces {
                parse_faces(d, s, &mut b)?;
            }
            Ok(b)
        })
        .collect::<R<Vec<_>>>()?;
    let taken: usize = w.edits.iter().map(|e| e.1 - e.0).sum();
    let mut out = Vec::with_capacity(d.len() - taken + 24 * w.edits.len());
    let mut at_ = 0;
    for &(s, e, n) in &w.edits {
        out.extend_from_slice(&d[at_..s]);
        out.extend_from_slice(b"[]");
        if let Some(n) = n {
            out.extend_from_slice(format!(",\"_njb\":{n}").as_bytes());
        }
        at_ = e;
    }
    out.extend_from_slice(&d[at_..]);
    Ok((out, blocks))
}
