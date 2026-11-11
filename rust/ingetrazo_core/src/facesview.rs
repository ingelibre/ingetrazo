// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! The geometry of every face of a view, for `core.vista_caras.view_faces`:
//! each face's rings taken to the world through its placement, its normal
//! (Newell, turned where the placement mirrors), cut to the kept side of
//! the section, drawn by the camera — parallel, or perspective through
//! the view pyramid — with its nearness plane fitted through the drawn
//! corners and its mean depth. The same steps in the same order as the
//! Python walk, face by face; the materials and colours stay there.

use rayon::prelude::*;

pub type Ring3 = Vec<[f64; 3]>;
pub type Ring2 = Vec<[f64; 2]>;

/// A face as it comes in: its rings (the loop first, then the holes) in
/// its mesh's coordinates, and the placement that takes them to the world
/// (`None`: already there).
pub struct FaceIn {
    pub rings: Vec<Ring3>,
    pub xform: Option<usize>,
}

/// The camera: a parallel one by its basis, a perspective one by its
/// clip matrix (row major), the eye and the picture plane's scale.
pub enum Camera {
    Parallel { eye: [f64; 3], right: [f64; 3], up: [f64; 3], fwd: [f64; 3] },
    Perspective { m: [[f64; 4]; 4], eye: [f64; 3], scale: [f64; 2] },
}

/// The kept side of the section plane: `n·p - c <= 1e-9`.
pub struct Section {
    pub n: [f64; 3],
    pub c: f64,
}

/// A face as it goes out, or nothing where the walk skipped it.
pub struct FaceOut {
    pub world: Vec<Ring3>,
    pub drawn: Vec<Ring2>,
    pub depths: Vec<Vec<f64>>,
    pub normal: [f64; 3],
    pub back: bool,
    pub near: [f64; 3],
    pub depth: f64,
}

#[inline]
fn dot(a: [f64; 3], b: [f64; 3]) -> f64 {
    a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
}

/// `p' = M[:3,:3]·p + M[:3,3]` — QMatrix4x4.map.
#[inline]
fn apply(m: &[[f64; 4]; 4], p: [f64; 3]) -> [f64; 3] {
    [
        m[0][0] * p[0] + m[0][1] * p[1] + m[0][2] * p[2] + m[0][3],
        m[1][0] * p[0] + m[1][1] * p[1] + m[1][2] * p[2] + m[1][3],
        m[2][0] * p[0] + m[2][1] * p[1] + m[2][2] * p[2] + m[2][3],
    ]
}

/// Whether a placement turns the loops round: the determinant of its
/// linear part is negative (`_mirrors`).
pub fn mirrors(m: &[[f64; 4]; 4]) -> bool {
    let d = m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
    d < 0.0
}

/// The unit normal of a world ring in its loop order (`_newell`), or
/// `None` for a degenerate one.
fn newell(r: &[[f64; 3]]) -> Option<[f64; 3]> {
    let n = r.len();
    let mut s = [0.0f64; 3];
    for k in 0..n {
        let a = r[k];
        let b = r[(k + 1) % n];
        s[0] += (a[1] - b[1]) * (a[2] + b[2]);
        s[1] += (a[2] - b[2]) * (a[0] + b[0]);
        s[2] += (a[0] - b[0]) * (a[1] + b[1]);
    }
    let ln = (s[0] * s[0] + s[1] * s[1] + s[2] * s[2]).sqrt();
    if ln > 1e-12 {
        Some([s[0] / ln, s[1] / ln, s[2] / ln])
    } else {
        None
    }
}

/// Sutherland–Hodgman of a world ring against the kept side of the
/// section (`_clip_ring_to_section`).
fn clip_to_section(pts: &[[f64; 3]], sp: &Section) -> Ring3 {
    let d: Vec<f64> = pts.iter().map(|p| dot(*p, sp.n) - sp.c).collect();
    if d.iter().all(|&v| v <= 1e-9) {
        return pts.to_vec();
    }
    if d.iter().all(|&v| v > 1e-9) {
        return Vec::new();
    }
    let n = pts.len();
    let mut out = Vec::with_capacity(n + 2);
    for i in 0..n {
        let j = (i + 1) % n;
        if d[i] <= 1e-9 {
            out.push(pts[i]);
        }
        if (d[i] <= 1e-9) != (d[j] <= 1e-9) {
            let t = d[i] / (d[i] - d[j]);
            out.push([
                pts[i][0] + (pts[j][0] - pts[i][0]) * t,
                pts[i][1] + (pts[j][1] - pts[i][1]) * t,
                pts[i][2] + (pts[j][2] - pts[i][2]) * t,
            ]);
        }
    }
    out
}

/// The view pyramid in clip space, rows `a` with the kept side `a·p >= 0`:
/// left, right, bottom, top, near (`core.hlr._PYRAMID`).
const PYRAMID: [[f64; 4]; 5] = [
    [1.0, 0.0, 0.0, 1.0],
    [-1.0, 0.0, 0.0, 1.0],
    [0.0, 1.0, 0.0, 1.0],
    [0.0, -1.0, 0.0, 1.0],
    [0.0, 0.0, 1.0, 1.0],
];

/// Sutherland–Hodgman against the view pyramid, in clip space
/// (`core.hlr._clip_polygon`).
fn clip_polygon(mut poly: Vec<[f64; 4]>) -> Vec<[f64; 4]> {
    for a in PYRAMID.iter() {
        let n = poly.len();
        let mut out = Vec::with_capacity(n + 2);
        for i in 0..n {
            let p = poly[i];
            let q = poly[(i + 1) % n];
            let dp = a[0] * p[0] + a[1] * p[1] + a[2] * p[2] + a[3] * p[3];
            let dq = a[0] * q[0] + a[1] * q[1] + a[2] * q[2] + a[3] * q[3];
            if dp >= 0.0 {
                out.push(p);
            }
            if (dp >= 0.0) != (dq >= 0.0) {
                let t = dp / (dp - dq);
                out.push([
                    p[0] + (q[0] - p[0]) * t,
                    p[1] + (q[1] - p[1]) * t,
                    p[2] + (q[2] - p[2]) * t,
                    p[3] + (q[3] - p[3]) * t,
                ]);
            }
        }
        poly = out;
        if poly.len() < 3 {
            return Vec::new();
        }
    }
    poly
}

impl Camera {
    fn facing_back(&self, normal: [f64; 3], centre: [f64; 3]) -> bool {
        match self {
            Camera::Parallel { fwd, .. } => dot(normal, *fwd) > 0.0,
            Camera::Perspective { eye, .. } => {
                dot(normal, [centre[0] - eye[0], centre[1] - eye[1], centre[2] - eye[2]]) > 0.0
            }
        }
    }

    /// World ring → drawn ring and depths (`_Parallel.ring` /
    /// `_Perspective.ring`): in perspective, cut to the pyramid first,
    /// then `(x / w, y / w)` scaled and `w` as the depth.
    fn ring(&self, pts: &[[f64; 3]]) -> (Ring2, Vec<f64>) {
        match self {
            Camera::Parallel { eye, right, up, fwd } => {
                let mut xy = Vec::with_capacity(pts.len());
                let mut dz = Vec::with_capacity(pts.len());
                for p in pts {
                    let d = [p[0] - eye[0], p[1] - eye[1], p[2] - eye[2]];
                    xy.push([dot(d, *right), dot(d, *up)]);
                    dz.push(dot(d, *fwd));
                }
                (xy, dz)
            }
            Camera::Perspective { m, scale, .. } => {
                let clip: Vec<[f64; 4]> = pts
                    .iter()
                    .map(|p| {
                        let mut c = [0.0f64; 4];
                        for r in 0..4 {
                            c[r] = m[r][0] * p[0] + m[r][1] * p[1] + m[r][2] * p[2] + m[r][3];
                        }
                        c
                    })
                    .collect();
                let poly = clip_polygon(clip);
                if poly.len() < 3 {
                    return (Vec::new(), Vec::new());
                }
                let xy = poly.iter().map(|c| [c[0] / c[3] * scale[0], c[1] / c[3] * scale[1]]).collect();
                let w = poly.iter().map(|c| c[3]).collect();
                (xy, w)
            }
        }
    }
}

/// Twice the signed area of a drawn ring, halved: `_area`.
fn area(r: &[[f64; 2]]) -> f64 {
    let n = r.len();
    let mut s = 0.0;
    for k in 0..n {
        let m = (k + 1) % n;
        s += r[k][0] * r[m][1] - r[m][0] * r[k][1];
    }
    0.5 * s
}

/// `(a, b, c)` with `a·x + b·y + c ≈ q` through every drawn corner, least
/// squares (`_nearness_plane`): the normal equations, solved exactly.
/// `None` where the corners do not span a plane.
fn nearness(rings: &[Ring2], depths: &[Vec<f64>], perspective: bool) -> Option<[f64; 3]> {
    // Fitted about the corners' mean, for the conditioning the plain
    // least squares has.
    let mut n = 0usize;
    let (mut mx, mut my) = (0.0f64, 0.0f64);
    for r in rings {
        for p in r {
            mx += p[0];
            my += p[1];
            n += 1;
        }
    }
    if n < 3 {
        return None;
    }
    mx /= n as f64;
    my /= n as f64;
    let (mut sxx, mut sxy, mut syy, mut sx, mut sy, mut sq, mut sxq, mut syq) =
        (0.0f64, 0.0f64, 0.0f64, 0.0f64, 0.0f64, 0.0f64, 0.0f64, 0.0f64);
    for (r, d) in rings.iter().zip(depths) {
        for (p, &dz) in r.iter().zip(d) {
            let q = if perspective { 1.0 / dz } else { -dz };
            let (x, y) = (p[0] - mx, p[1] - my);
            sxx += x * x;
            sxy += x * y;
            syy += y * y;
            sx += x;
            sy += y;
            sq += q;
            sxq += x * q;
            syq += y * q;
        }
    }
    // [sxx sxy sx; sxy syy sy; sx sy n]·[a b c'] = [sxq syq sq]
    let nn = n as f64;
    let m = [[sxx, sxy, sx], [sxy, syy, sy], [sx, sy, nn]];
    let rhs = [sxq, syq, sq];
    let det = m[0][0] * (m[1][1] * m[2][2] - m[1][2] * m[2][1])
        - m[0][1] * (m[1][0] * m[2][2] - m[1][2] * m[2][0])
        + m[0][2] * (m[1][0] * m[2][1] - m[1][1] * m[2][0]);
    let scale = (sxx + syy).max(1e-300) * nn;
    if det.abs() <= 1e-18 * scale * scale {
        return None;
    }
    let solve = |col: usize| {
        let mut mm = m;
        for r in 0..3 {
            mm[r][col] = rhs[r];
        }
        (mm[0][0] * (mm[1][1] * mm[2][2] - mm[1][2] * mm[2][1])
            - mm[0][1] * (mm[1][0] * mm[2][2] - mm[1][2] * mm[2][0])
            + mm[0][2] * (mm[1][0] * mm[2][1] - mm[1][1] * mm[2][0]))
            / det
    };
    let a = solve(0);
    let b = solve(1);
    let c = solve(2) - a * mx - b * my;
    Some([a, b, c])
}

/// One face through the walk's steps; `None` where the walk `continue`d.
fn one(f: &FaceIn, xforms: &[[[f64; 4]; 4]], cam: &Camera, section: Option<&Section>) -> Option<FaceOut> {
    let perspective = matches!(cam, Camera::Perspective { .. });
    let mut world: Vec<Ring3> = Vec::with_capacity(f.rings.len());
    for r in &f.rings {
        world.push(match f.xform {
            Some(k) => r.iter().map(|p| apply(&xforms[k], *p)).collect(),
            None => r.clone(),
        });
    }
    if world.is_empty() || world[0].len() < 3 {
        return None;
    }
    let mut normal = newell(&world[0])?;
    if let Some(k) = f.xform {
        if mirrors(&xforms[k]) {
            normal = [-normal[0], -normal[1], -normal[2]];
        }
    }
    if let Some(sp) = section {
        let cut: Vec<Ring3> = world.iter().map(|r| clip_to_section(r, sp)).filter(|r| r.len() >= 3).collect();
        if cut.is_empty() || cut[0].len() < 3 {
            return None;
        }
        world = cut;
    }
    let mut centre = [0.0f64; 3];
    for p in &world[0] {
        centre[0] += p[0];
        centre[1] += p[1];
        centre[2] += p[2];
    }
    let n0 = world[0].len() as f64;
    centre = [centre[0] / n0, centre[1] / n0, centre[2] / n0];
    let back = cam.facing_back(normal, centre);
    let mut drawn: Vec<Ring2> = Vec::with_capacity(world.len());
    let mut depths: Vec<Vec<f64>> = Vec::with_capacity(world.len());
    for r in &world {
        let (xy, dz) = cam.ring(r);
        if xy.len() >= 3 {
            drawn.push(xy);
            depths.push(dz);
        }
    }
    // A face the camera draws nothing of, or seen edge on, still stands
    // in the sun: its world rings go back with no drawing (the walk had
    // listed it among the casters before it `continue`d).
    let nothing = |world: Vec<Ring3>| {
        Some(FaceOut { world, drawn: Vec::new(), depths: Vec::new(), normal, back, near: [f64::NAN; 3], depth: f64::NAN })
    };
    if drawn.is_empty() || area(&drawn[0]).abs() < 1e-12 {
        return nothing(world);
    }
    let near = match nearness(&drawn, &depths, perspective) {
        Some(v) => v,
        None => return nothing(world),
    };
    let (mut sum, mut cnt) = (0.0f64, 0usize);
    for d in &depths {
        for v in d {
            sum += v;
            cnt += 1;
        }
    }
    Some(FaceOut { world, drawn, depths, normal, back, near, depth: sum / cnt as f64 })
}

/// Every face, in parallel, each in its place (`None` where skipped).
pub fn faces_view(faces: &[FaceIn], xforms: &[[[f64; 4]; 4]], cam: &Camera, section: Option<&Section>) -> Vec<Option<FaceOut>> {
    faces.par_iter().map(|f| one(f, xforms, cam, section)).collect()
}
