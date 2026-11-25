# Production-oriented API consumer: OpenTrace BIM

[OpenTrace BIM](https://github.com/lelopes05/ingetrazo-parametric-architecture) is an actively developed parametric architecture/BIM toolkit for IngeTrazo and the first production-oriented consumer driving the requirements of this Resource / Library API proposal.

It is deliberately more demanding than a minimal API demo. The current user-tested toolkit already includes straight and curved parametric walls, hosted openings including curved walls, multilayer wall and slab assemblies, editable slabs and slab openings, parametric columns and beams, reusable Complex Profiles, level anchoring, contextual editing and persistence inside `.igz` documents.

A companion Layer Combinations module already manages named layer combinations, visibility and lock state, virtual folders, per-layer intersection groups, project templates, personal templates and portable import/export.

## Why this matters to the generic API

OpenTrace BIM needs reusable architectural resources without moving architecture-specific semantics into IngeTrazo core. Examples include:

- wall and slab construction assemblies;
- complete element presets;
- complex beam/column profiles;
- structural profile catalogues;
- office libraries shared between projects;
- resources with dependencies;
- portable bundles that do not depend on another workstation having the same local favourites.

That is why the proposed core API remains generic: the host provides resource discovery, IDs, libraries, dependencies, search and portable bundles; the extension owns architectural schemas, validation, editing and geometry.

## Public development status

**Current user-tested baseline:** `0.10.2-dev-profile-library-ui`

**Current development snapshot:** `0.11` pre-alpha, under real-world testing.

The 0.11 snapshot adds a unified OpenTrace BIM workspace, assembly presets, structural profile catalogue work, profile folders/categories and deeper Layer Combinations integration.

- [Feature matrix](https://github.com/lelopes05/ingetrazo-parametric-architecture/blob/main/FEATURES.md)
- [Public roadmap](https://github.com/lelopes05/ingetrazo-parametric-architecture/blob/main/ROADMAP.md)

## Development previews

These are UI concept mockups, not runtime screenshots.

![OpenTrace BIM workspace](https://raw.githubusercontent.com/lelopes05/ingetrazo-parametric-architecture/main/docs/images/opentrace-overview.svg)

![OpenTrace BIM profile library](https://raw.githubusercontent.com/lelopes05/ingetrazo-parametric-architecture/main/docs/images/opentrace-profile-library.svg)

![OpenTrace BIM Layer Combinations](https://raw.githubusercontent.com/lelopes05/ingetrazo-parametric-architecture/main/docs/images/opentrace-layer-combinations.svg)

## Coordination

The OpenTrace BIM repository and roadmap are intentionally public while development is active.

Architecture/BIM subsystems are large enough that parallel implementations can easily duplicate substantial work. Contributors working on overlapping walls, slabs, columns, beams, profiles, junctions, quantities, grids, MEP or library/resource systems are encouraged to make that work visible early so implementations can be compared, reused or coordinated before both are already complete.
