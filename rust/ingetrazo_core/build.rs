// The module carries a fingerprint of the sources it was built from, so a
// test can tell an installed module that no longer matches rust/ (a stale
// build would measure yesterday's kernels). FNV-1a 64 over Cargo.toml,
// Cargo.lock and src/*.rs by name, CR dropped; tests/test_rust_engine_switch
// computes the same.
use std::fs;
use std::path::Path;

fn main() {
    let mut files = vec!["Cargo.toml".to_string(), "Cargo.lock".to_string()];
    let mut srcs: Vec<String> = fs::read_dir("src")
        .unwrap()
        .filter_map(|e| e.ok())
        .map(|e| e.file_name().to_string_lossy().into_owned())
        .filter(|n| n.ends_with(".rs"))
        .map(|n| format!("src/{n}"))
        .collect();
    srcs.sort();
    files.extend(srcs);
    let mut h: u64 = 0xcbf29ce484222325;
    for f in &files {
        println!("cargo:rerun-if-changed={f}");
        let bytes = fs::read(Path::new(f)).unwrap();
        for &b in f.as_bytes().iter().chain([0u8].iter()).chain(bytes.iter()) {
            if b == b'\r' {
                continue;
            }
            h ^= b as u64;
            h = h.wrapping_mul(0x100000001b3);
        }
    }
    println!("cargo:rerun-if-changed=src");
    println!("cargo:rustc-env=INGETRAZO_SOURCE_HASH={h:016x}");
}
