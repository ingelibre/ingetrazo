# Portable resource bundles

The experimental portable container uses the `.iglib` extension.

An `.iglib` file is a ZIP archive with:

```text
manifest.json
resources/0000.bin
resources/0001.bin
...
```

The core owns the container, stable references, dependency order and conflict
handling. Extensions still own each resource payload.

## Export

`export_bundle(..., include_dependencies=True)` exports the selected resource
and its complete dependency closure in dependency-first order.

## Import conflict policy

- `error`: stop on an existing ID with a different version.
- `skip`: preserve the local resource.
- `replace`: pass the incoming payload to the provider.

The same ID and same version are always skipped.

The bundle has its own format version, independent from both the extension API
version and the version of an individual resource.
