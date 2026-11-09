# Reopening named curves from IGZ documents

Some documents written by IngeTrazo 0.5.8 contain textual edge `curve`
identifiers in their JSON mesh blocks. Saving these small meshes succeeds,
but reopening compares the stored string with the integer curve counter and
raises `TypeError: '>=' not supported between instances of 'str' and 'int'`.
Mixed string/integer IDs can also fail in the bulk JSON loader. A format-3
container can carry these JSON meshes beside its binary geometry blocks.

The loader now normalizes textual identities before constructing geometry.
Each distinct string receives one integer shared by its segments. Existing
integer IDs are reserved across the entire document, including prototypes,
nested groups, kept components and binary meshes, before allocating the new
IDs. This keeps names such as `"01"` and `"1"` distinct from integer `1` and
from each other, and keeps subsequently drawn curves unique.

Normalization visits only geometry that the loader consumes. Extension and
plugin metadata retain their own values. Ordinary binary documents incur no
additional binary-array validation. Loaded curves can subsequently be saved
as JSON or integer-backed binary geometry using the existing format.

Regression coverage in `tests/test_igz_curve_ids.py` exercises small and bulk
JSON loading, plain and ZIP documents, mixed textual/numeric IDs, nested and
shared geometry, binary ID reservations and both save/reopen paths. The
unmodified loader fails the first regression with the reported TypeError.

Validation on macOS: 79 focused tests passed. The reported document also
loaded, saved to a separate copy and reopened with matching counts of
groups, meshes, edges, faces and curve segments. Its original bytes remained
unchanged.

The rebuilt, installed macOS app opened the original Linux-saved document
through its native file dialog and displayed the complete model. The fast
suite completed with 4,576 passed, 29 skipped and 805 deselected, plus the
previously reproduced baseline failure in
`test_extension_manager.py::test_long_author_tags_and_license_wrap_within_preview_width`.
That full-suite run used the original local checkout based on `d8ee8c0`,
including the separate macOS accessibility fix (#657). The 79 focused tests
were also repeated successfully on the independent branch based on current
`main` before opening this PR.
