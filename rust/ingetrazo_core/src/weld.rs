// SPDX-License-Identifier: GPL-3.0-or-later
// Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
//! `core.lazy_mesh.weld` — what `Mesh.bulk_weld` makes of a batch of
//! points on an EMPTY mesh — with a hash map in place of the NumPy sorts:
//! the same cells (`np.round`, ties to even, of the float32 positions ×
//! 10⁴), the same "candidate" cells (a neighbouring cell in the batch),
//! one vertex per lone cell at its first point, and the candidates
//! replayed point by point with the 26-cell probe and Qt's float32
//! squared distance.

use std::collections::HashMap;

type Cell = (i64, i64, i64);

/// ``(vertex positions as float32, point → vertex, the point each vertex
/// was made at)``, vertices in the order bulk_weld's vertex list holds
/// them.
pub fn weld(pos: &[[f32; 3]], scale: f64, tol2: f64) -> (Vec<[f32; 3]>, Vec<i64>, Vec<i64>) {
    let n = pos.len();
    let mut cell_of: Vec<Cell> = Vec::with_capacity(n);
    let mut index: HashMap<Cell, usize> = HashMap::with_capacity(n);
    let mut cells: Vec<Cell> = Vec::new();
    let mut first: Vec<usize> = Vec::new();
    let mut point_cell: Vec<usize> = Vec::with_capacity(n);
    for (i, p) in pos.iter().enumerate() {
        let c = (
            (p[0] as f64 * scale).round_ties_even() as i64,
            (p[1] as f64 * scale).round_ties_even() as i64,
            (p[2] as f64 * scale).round_ties_even() as i64,
        );
        cell_of.push(c);
        let k = *index.entry(c).or_insert_with(|| {
            cells.push(c);
            first.push(i);
            cells.len() - 1
        });
        point_cell.push(k);
    }
    let nu = cells.len();
    let mut candidate = vec![false; nu];
    for (u, c) in cells.iter().enumerate() {
        'probe: for dx in -1..=1i64 {
            for dy in -1..=1i64 {
                for dz in -1..=1i64 {
                    if dx == 0 && dy == 0 && dz == 0 {
                        continue;
                    }
                    if index.contains_key(&(c.0 + dx, c.1 + dy, c.2 + dz)) {
                        candidate[u] = true;
                        break 'probe;
                    }
                }
            }
        }
    }
    // Lone cells first, in creation order: one vertex each.
    let mut vpos: Vec<[f32; 3]> = Vec::new();
    let mut origin: Vec<i64> = Vec::new();
    let mut cell_vid = vec![-1i64; nu];
    let mut registry: HashMap<Cell, usize> = HashMap::new();
    for u in 0..nu {
        if !candidate[u] {
            cell_vid[u] = vpos.len() as i64;
            registry.insert(cells[u], vpos.len());
            vpos.push(pos[first[u]]);
            origin.push(first[u] as i64);
        }
    }
    let mut ids = vec![0i64; n];
    for i in 0..n {
        let u = point_cell[i];
        if !candidate[u] {
            ids[i] = cell_vid[u];
        }
    }
    // Candidate points, replayed in input order.
    for i in 0..n {
        let u = point_cell[i];
        if !candidate[u] {
            continue;
        }
        let k = cell_of[i];
        let vid = match registry.get(&k) {
            Some(&v) => v,
            None => {
                let p = pos[i];
                let mut hit: Option<usize> = None;
                'near: for dx in -1..=1i64 {
                    for dy in -1..=1i64 {
                        for dz in -1..=1i64 {
                            if dx == 0 && dy == 0 && dz == 0 {
                                continue;
                            }
                            if let Some(&nb) = registry.get(&(k.0 + dx, k.1 + dy, k.2 + dz)) {
                                let q = vpos[nb];
                                let d = [q[0] - p[0], q[1] - p[1], q[2] - p[2]];
                                let l2 = d[0] * d[0] + d[1] * d[1] + d[2] * d[2];
                                if (l2 as f64) < tol2 {
                                    hit = Some(nb);
                                    break 'near;
                                }
                            }
                        }
                    }
                }
                match hit {
                    Some(v) => v,
                    None => {
                        let v = vpos.len();
                        vpos.push(p);
                        origin.push(i as i64);
                        registry.insert(k, v);
                        v
                    }
                }
            }
        };
        ids[i] = vid as i64;
    }
    (vpos, ids, origin)
}
