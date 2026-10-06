# Extension resource/library API (experimental)

The IngeTrazo core remains domain-neutral: it does not need to know what a
wall, profile, material, family or preset means.

## This block adds

- lightweight resource metadata separated from heavy payloads;
- multiple library/source descriptions (personal, project, shared, remote);
- stable resource references with optional versions;
- dependency graphs across resource types;
- cycle and missing-dependency protection;
- lightweight search that never loads the full resource;
- optional import/export capabilities.

The provider still owns the actual storage and domain format.

## Required provider methods

```python
list_resources()
get_resource(resource_id)
```

## Optional provider methods

```python
list_libraries()
get_dependencies(resource_id)
export_resource(resource_id)
import_resource(payload)
```

## Portable bundles

`core.resource_bundle` adds the experimental `.iglib` container for exporting
one resource with its dependencies and importing it elsewhere. See
`docs/resource_bundle.md`.

## Production-oriented API consumer

The first production-oriented consumer driving these requirements is
[OpenTrace BIM](docs/opentrace_bim_consumer.md), an actively developed
parametric architecture/BIM toolkit for IngeTrazo. Its real resource cases
include construction assemblies, complete element presets, reusable complex
profiles, structural catalogues and portable office libraries.

Keeping those architectural schemas in the extension while the core owns only
generic discovery, dependency and portability mechanics is the intended API
boundary.
