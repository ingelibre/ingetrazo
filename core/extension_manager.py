# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Catalog-backed install and update operations for third-party extensions."""
from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import shutil
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from core.extensions import user_plugins_dir
from core.version import USER_AGENT, __version__

CATALOG_URL = (
    "https://raw.githubusercontent.com/ingelibre/"
    "ingetrazo-extensions/main/catalog.json")
REVIEWED_URL = (
    "https://raw.githubusercontent.com/ingelibre/"
    "ingetrazo-extensions/main/reviewed.toml")
TIMEOUT = 20
MAX_CATALOG_BYTES = 2 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_ARCHIVE_FILES = 2000
MAX_EXTRACTED_BYTES = 128 * 1024 * 1024
_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{64}$")


class ExtensionManagerError(Exception):
    """A catalog or installation operation could not be completed safely."""


@dataclass(frozen=True)
class Extension:
    id: str
    version: str
    author: str
    license: str
    repository: str
    download: str
    sha256: str
    minimum_version: str
    name: dict[str, str]
    summary: dict[str, str]
    tags: tuple[str, ...]
    screenshot: str | None = None
    updated_at: str | None = None
    #: An extension that ships inside IngeTrazo (``examples/extensions``):
    #: the local file or folder it installs from — nothing is downloaded.
    bundled: str | None = None


@dataclass(frozen=True)
class CatalogSnapshot:
    extensions: list[Extension]
    reviewed: dict[str, dict]
    fetched_at: str
    from_cache: bool


def _get(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            if not response.geturl().startswith("https://"):
                raise ExtensionManagerError(
                    "The download redirected to a non-HTTPS address.")
            data = response.read(limit + 1)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ExtensionManagerError(f"Could not download {url}: {exc}") from exc
    if len(data) > limit:
        raise ExtensionManagerError("The downloaded file is too large.")
    return data


def _text_map(value, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
            isinstance(k, str) and isinstance(v, str)
            for k, v in value.items()):
        raise ExtensionManagerError(f"Invalid {field} in extension catalog.")
    return value


def _parse_extension(raw: object) -> Extension:
    if not isinstance(raw, dict):
        raise ExtensionManagerError("Invalid extension entry in catalog.")
    ident = raw.get("id")
    if not isinstance(ident, str) or not _ID_RE.fullmatch(ident):
        raise ExtensionManagerError("Invalid extension ID in catalog.")
    strings = ("version", "author", "license", "repository", "download",
               "sha256", "ingetrazo")
    if any(not isinstance(raw.get(key), str) or not raw[key]
           for key in strings):
        raise ExtensionManagerError(
            f"Extension {ident!r} has incomplete catalog metadata.")
    if not _SHA_RE.fullmatch(raw["sha256"]):
        raise ExtensionManagerError(
            f"Extension {ident!r} has an invalid SHA-256 digest.")
    if not raw["download"].startswith("https://"):
        raise ExtensionManagerError(
            f"Extension {ident!r} does not use an HTTPS download URL.")
    tags = raw.get("tags", [])
    if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
        raise ExtensionManagerError(f"Extension {ident!r} has invalid tags.")
    screenshot = raw.get("screenshot")
    if screenshot is not None and (
            not isinstance(screenshot, str)
            or "/" in screenshot or "\\" in screenshot
            or PurePosixPath(screenshot).suffix.lower() not in (
                ".png", ".jpg", ".jpeg", ".webp")):
        raise ExtensionManagerError(
            f"Extension {ident!r} has an invalid screenshot filename.")
    updated_at = raw.get("updated_at")
    if updated_at is not None and not isinstance(updated_at, str):
        raise ExtensionManagerError(
            f"Extension {ident!r} has an invalid update date.")
    return Extension(
        id=ident,
        version=raw["version"],
        author=raw["author"],
        license=raw["license"],
        repository=raw["repository"],
        download=raw["download"],
        sha256=raw["sha256"].lower(),
        minimum_version=raw["ingetrazo"],
        name=_text_map(raw.get("name"), "name"),
        summary=_text_map(raw.get("summary"), "summary"),
        tags=tuple(tags),
        screenshot=screenshot,
        updated_at=updated_at,
    )


def _parse_catalog(catalog_data: bytes, reviewed_data: bytes,
                   fetched_at: str, from_cache: bool) -> CatalogSnapshot:
    try:
        catalog = json.loads(catalog_data)
        import tomllib
        reviewed = tomllib.loads(reviewed_data.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ExtensionManagerError(
            f"The extension catalog is invalid: {exc}") from exc
    if not isinstance(catalog, dict) or catalog.get("format") != 1:
        raise ExtensionManagerError("Unsupported extension catalog format.")
    raw_extensions = catalog.get("extensions")
    if not isinstance(raw_extensions, list):
        raise ExtensionManagerError("The extension catalog has no entries.")
    extensions = [_parse_extension(raw) for raw in raw_extensions]
    ids = [extension.id for extension in extensions]
    if len(ids) != len(set(ids)):
        raise ExtensionManagerError("The catalog contains duplicate IDs.")
    if not isinstance(reviewed, dict):
        raise ExtensionManagerError("The reviewed-extension list is invalid.")
    return CatalogSnapshot(extensions, reviewed, fetched_at, from_cache)


def catalog_cache_path() -> Path:
    """Per-user cache for the catalog and its matching review hashes."""
    return user_plugins_dir().parent / "catalog-cache.json"


def load_cached_catalog() -> CatalogSnapshot | None:
    path = catalog_cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, ValueError) as exc:
        logging.getLogger("ingetrazo.extensions").warning(
            "could not read extension catalog cache %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logging.getLogger("ingetrazo.extensions").warning(
            "invalid extension catalog cache at %s", path)
        return None
    catalog_data = data.get("catalog")
    reviewed_data = data.get("reviewed")
    fetched_at = data.get("fetched_at")
    if (not isinstance(catalog_data, dict)
            or not isinstance(reviewed_data, str)
            or not isinstance(fetched_at, str)):
        logging.getLogger("ingetrazo.extensions").warning(
            "incomplete extension catalog cache at %s", path)
        return None
    try:
        return _parse_catalog(
            json.dumps(catalog_data).encode("utf-8"),
            reviewed_data.encode("utf-8"), fetched_at, True)
    except ExtensionManagerError as exc:
        logging.getLogger("ingetrazo.extensions").warning(
            "invalid extension catalog cache %s: %s", path, exc)
        return None


def refresh_catalog() -> CatalogSnapshot:
    """Fetch and validate online catalog data, caching a complete snapshot.

    If the network is unavailable, a previously validated cache is returned
    instead. With no usable cache, the original network error is raised.
    """
    try:
        catalog_data = _get(CATALOG_URL, MAX_CATALOG_BYTES)
        reviewed_data = _get(REVIEWED_URL, MAX_CATALOG_BYTES)
        fetched_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        snapshot = _parse_catalog(
            catalog_data, reviewed_data, fetched_at, False)
    except (ExtensionManagerError, OSError) as exc:
        cached = load_cached_catalog()
        if cached is not None:
            logging.getLogger("ingetrazo.extensions").info(
                "using cached extension catalog after refresh failed: %s",
                exc)
            return cached
        raise

    path = catalog_cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_text(json.dumps({
            "catalog": json.loads(catalog_data),
            "reviewed": reviewed_data.decode("utf-8"),
            "fetched_at": fetched_at,
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(path)
    except OSError:
        logging.getLogger("ingetrazo.extensions").warning(
            "could not cache extension catalog at %s", path, exc_info=True)
    return snapshot


def load_catalog() -> tuple[list[Extension], dict[str, dict]]:
    """Compatibility wrapper returning catalog entries and review hashes."""
    snapshot = refresh_catalog()
    return snapshot.extensions, snapshot.reviewed


def display_name(extension: Extension, language: str) -> str:
    lang = language.lower().replace("_", "-").split("-", 1)[0]
    return (extension.name.get(lang) or extension.name.get("en")
            or next(iter(extension.name.values()), extension.id))


def display_summary(extension: Extension, language: str) -> str:
    lang = language.lower().replace("_", "-").split("-", 1)[0]
    return (extension.summary.get(lang) or extension.summary.get("en")
            or next(iter(extension.summary.values()), ""))


def is_reviewed(extension: Extension, reviewed: dict[str, dict]) -> bool:
    entry = reviewed.get(extension.id)
    return (isinstance(entry, dict)
            and str(entry.get("sha256", "")).lower() == extension.sha256)


def _managed_target(ident: str) -> tuple[Path, bool]:
    root = user_plugins_dir()
    folder = root / ident
    flat = root / f"{ident}.py"
    if folder.exists():
        if folder.is_symlink():
            return folder, False
        metadata = folder / "extension.json"
        if not folder.is_dir() or not metadata.is_file():
            return folder, False
        try:
            data = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return folder, False
        return folder, isinstance(data, dict) and data.get("id") == ident
    if flat.exists():
        if flat.is_symlink():
            return flat, False
        return flat, False
    return folder, True


def installed_info(ident: str) -> dict | None:
    target, managed = _managed_target(ident)
    if not target.exists() or not managed or target.is_file():
        return None
    try:
        data = json.loads((target / "extension.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def extension_startup_state() -> dict[str, dict]:
    """Snapshot managed extension files and enabled state for this app run."""
    root = user_plugins_dir()
    try:
        entries = list(root.iterdir())
    except FileNotFoundError:
        return {}
    except OSError:
        logging.getLogger("ingetrazo.extensions").warning(
            "could not read installed extensions at startup: %s",
            root, exc_info=True)
        return {}

    state = {}
    for folder in entries:
        if (folder.name.startswith(".") or folder.is_symlink()
                or not folder.is_dir()):
            continue
        try:
            metadata = json.loads((folder / "extension.json").read_text(
                encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(metadata, dict):
            continue
        ident = metadata.get("id")
        if not isinstance(ident, str) or not _ID_RE.fullmatch(ident):
            continue
        state[ident] = {
            "sha256": metadata.get("sha256"),
            "enabled": not (folder / ".disabled").is_file(),
        }
    return state


def restart_required(ident: str, startup_state: dict[str, dict]) -> bool:
    """Whether the current installation differs from what this run started."""
    current = installed_info(ident)
    startup = startup_state.get(ident)
    if current is None:
        return startup is not None
    was_enabled = bool(startup and startup.get("enabled"))
    enabled = is_extension_enabled(ident)
    if enabled != was_enabled:
        return True
    return enabled and (
        startup is None or current.get("sha256") != startup.get("sha256"))


def installation_conflict(ident: str) -> bool:
    target, managed = _managed_target(ident)
    return target.exists() and not managed


def uninstall_extension(ident: str) -> None:
    """Remove an extension only when its directory is manager-owned."""
    target, managed = _managed_target(ident)
    if not target.exists() or not managed or not target.is_dir():
        raise ExtensionManagerError(
            f"{ident!r} is not an installed extension managed by IngeTrazo.")
    shutil.rmtree(target)


def _python_fingerprint(path: Path) -> tuple[str | None, frozenset[str]]:
    """``(sha256 of the entry module, the package's module paths)`` of an
    installed plugin — a loose ``x.py`` or a package folder."""
    def digest(file: Path) -> str | None:
        try:
            return hashlib.sha256(file.read_bytes()).hexdigest()
        except OSError:
            return None
    if path.is_file():
        return digest(path), frozenset()
    modules = frozenset(
        p.relative_to(path).as_posix() for p in path.rglob("*.py")
        if "__pycache__" not in p.parts and p.name != "__init__.py")
    return digest(path / "__init__.py"), modules


def retired_extensions(catalog_ids: Iterable[str]) -> list[Path]:
    """Folders the manager installed whose id the catalog no longer lists —
    renamed or withdrawn since. The catalog has no card for them, so the
    manager lists them on their own to disable or uninstall."""
    known = set(catalog_ids)
    try:
        candidates = sorted(user_plugins_dir().iterdir())
    except OSError:
        return []
    return [path for path in candidates
            if path.name not in known and not path.name.startswith(("_", "."))
            and _ID_RE.fullmatch(path.name) and installed_info(path.name)]


def manual_copies(ident: str, package: Path,
                  catalog_ids: Iterable[str] | None = None) -> list[Path]:
    """Plugins installed by hand that look like ``package`` under another
    name — OpenTrace used to be unpacked as ``arquitetura_parametrica``,
    and installing it from the catalog as ``opentrace_bim`` then loaded it
    twice. The same entry module, or most of the same module files (an
    older or newer version of it), counts as a copy. With ``catalog_ids``,
    a folder the manager installed under an id the catalog no longer lists
    counts too: it is the same extension under its old name."""
    entry, modules = _python_fingerprint(package)
    found = []
    try:
        candidates = sorted(user_plugins_dir().iterdir())
    except OSError:
        return []
    retired_paths = (set() if catalog_ids is None
                     else set(retired_extensions(catalog_ids)))
    for path in candidates:
        if (path.name.startswith(("_", ".")) or path.is_symlink()
                or path.name in (ident, f"{ident}.py")):
            continue
        if path.is_dir():
            managed = (path / "extension.json").is_file()
            if ((managed and path not in retired_paths)
                    or not (path / "__init__.py").is_file()):
                continue
        elif path.suffix != ".py":
            continue
        other_entry, other_modules = _python_fingerprint(path)
        same_entry = entry is not None and entry == other_entry
        shared = len(modules & other_modules)
        similar = (len(modules) >= 3 and len(other_modules) >= 3
                   and shared / len(modules | other_modules) >= 0.6)
        if same_entry or similar:
            found.append(path)
    return found


def _set_aside(path: Path) -> Path:
    """Rename a hand-installed copy so the loader skips it (dot names are
    never loaded) — kept, not deleted, so it can be put back."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f".{path.name}.manual-{stamp}")
    path.replace(target)
    return target


def example_extension_files() -> list[tuple[Path, str, str]]:
    """``(path, title, blurb)`` of each extension shipped with the app in
    ``examples/extensions`` — never loaded on their own: what only some
    need stays out of the core, and the manager installs it on request."""
    return [(path, title, blurb)
            for path, title, blurb, _tagline in _example_entries()]


def _example_entries() -> list[tuple[Path, str, str, str]]:
    """``(path, title, blurb, tagline)``: the tagline is what the first
    docstring line says after the title («Windowizer — parametric windows
    from selected faces.»), the card's one-line summary."""
    import ast
    from core.paths import app_root
    folder = app_root() / "examples" / "extensions"
    out = []
    # A single ``x.py`` or a package ``x/__init__.py`` — a bigger
    # extension (CAM, PR #132) is a folder, and the loader takes both.
    entries = sorted(folder.iterdir()) if folder.is_dir() else []
    for path in entries:
        if path.suffix == ".py" and path.is_file():
            src = path
        elif path.is_dir() and (path / "__init__.py").is_file():
            src = path / "__init__.py"
        else:
            continue
        try:
            doc = ast.get_docstring(ast.parse(src.read_text("utf-8"))) or ""
        except (OSError, SyntaxError, ValueError):
            doc = ""
        first, _, rest = doc.partition("\n")
        title, _, tagline = first.partition(" — ")
        title = title.strip() or path.stem
        blurb = rest.strip().split("\n\n")[0].replace("\n", " ")
        tagline = tagline.strip()
        tagline = (tagline[:1].upper() + tagline[1:]) if tagline else blurb
        out.append((path, title, blurb, tagline))
    return out


def _example_screenshot(path: Path) -> str | None:
    """The preview shipped beside an example: ``windowizer.png`` next to
    ``windowizer.py``, or ``screenshot.png`` inside a package."""
    folder, stem = ((path, "screenshot") if path.is_dir()
                    else (path.parent, path.stem))
    for suffix in (".png", ".jpg", ".jpeg", ".webp"):
        image = folder / f"{stem}{suffix}"
        if image.is_file():
            return str(image)
    return None


def _bundle_digest(path: Path) -> str:
    """SHA-256 of a bundled extension: the file, or every file of the
    package in a fixed order — it changes when an update of IngeTrazo
    brings a new version, so the manager offers to update the copy."""
    h = hashlib.sha256()
    if path.is_file():
        h.update(path.read_bytes())
        return h.hexdigest()
    for file in sorted(p for p in path.rglob("*") if p.is_file()
                       and "__pycache__" not in p.parts
                       and p.suffix != ".pyc"):
        h.update(file.relative_to(path).as_posix().encode())
        h.update(b"\0")
        h.update(file.read_bytes())
    return h.hexdigest()


def bundled_extensions() -> list[Extension]:
    """The extensions shipped with IngeTrazo, as manager entries: installed
    from the local copy, managed like a catalog one from then on (update,
    disable, uninstall). A catalog entry with the same id wins over it."""
    from core.i18n import current_language, tr
    from core.version import __version__
    lang = current_language().lower().replace("_", "-").split("-", 1)[0]
    out = []
    for path, title, _blurb, tagline in _example_entries():
        ident = path.stem if path.suffix == ".py" else path.name
        try:
            digest = _bundle_digest(path)
        except OSError:
            continue
        out.append(Extension(
            id=ident, version=__version__, author="IngeTrazo", license="",
            repository="", download="", sha256=digest,
            minimum_version=__version__, name={"en": title},
            summary={"en": tagline, lang: tr(tagline)}, tags=(),
            screenshot=_example_screenshot(path), bundled=str(path)))
    return out


def hand_installed_plugins() -> list[Path]:
    """Plugins in the user folder that the manager did not install: a
    package folder without ``extension.json`` or a loose ``x.py``. Until
    0.5.8 copying the folder by hand was the only way to install one, so
    every extension a user had then shows up here."""
    try:
        candidates = sorted(user_plugins_dir().iterdir())
    except OSError:
        return []
    found = []
    for path in candidates:
        if path.name.startswith(("_", ".")):
            continue                      # __pycache__, set-aside copies
        if path.is_dir():
            if ((path / "extension.json").is_file()
                    or not (path / "__init__.py").is_file()):
                continue
        elif path.suffix != ".py":
            continue
        found.append(path)
    return found


def hand_installed_ident(path: Path) -> str:
    """The plugin name the loader knows a hand-installed copy by."""
    return path.stem if path.suffix == ".py" else path.name


def remove_hand_installed(path: Path) -> Path:
    """Uninstall a hand-installed plugin by setting it aside — renamed
    with a dot in front, in the same folder, never deleted: the manager
    did not put it there, so it does not destroy it. Returns the new
    path; the loader skips dot names from the next start."""
    root = user_plugins_dir()
    if path.parent != root or path not in hand_installed_plugins():
        raise ExtensionManagerError(
            f"{path.name!r} is not a plugin installed by hand.")
    return _set_aside(path)


def replace_hand_installed(extension: Extension,
                           confirm_manual_copies=None,
                           catalog_ids: Iterable[str] | None = None
                           ) -> list[Path]:
    """Install ``extension`` from the catalog over a copy installed by
    hand under the same name: the copy is set aside first, then the
    catalog version installs as a managed one. If the install fails, the
    copy is put back where it was. Returns where the copy went."""
    root = user_plugins_dir()
    own = [p for p in hand_installed_plugins()
           if hand_installed_ident(p) == extension.id and p.parent == root]
    moved = [(p, _set_aside(p)) for p in own]
    try:
        install_extension(extension, confirm_manual_copies, catalog_ids)
    except Exception:
        for original, aside in reversed(moved):
            try:
                aside.replace(original)
            except OSError:
                logging.getLogger("ingetrazo.extensions").warning(
                    "could not put back %s as %s", aside, original,
                    exc_info=True)
        raise
    return [aside for _original, aside in moved]


def install_extension(extension: Extension,
                      confirm_manual_copies=None,
                      catalog_ids: Iterable[str] | None = None) -> None:
    """Download, verify and atomically install an extension or its update.

    If the same extension is already installed by hand under another name,
    ``confirm_manual_copies(paths)`` decides: True sets those copies aside
    (renamed, not deleted) and installs; False — or no callback — installs
    nothing, so the extension never loads twice. ``catalog_ids`` lets a
    managed copy under an id the catalog dropped count as such a copy."""
    if not compatible_with_current(extension):
        raise ExtensionManagerError(
            f"{extension.id!r} requires IngeTrazo "
            f"{extension.minimum_version} or later.")
    target, managed = _managed_target(extension.id)
    if not managed:
        raise ExtensionManagerError(
            f"A plugin named {extension.id!r} already exists and is not "
            "managed by the extension manager.")
    source = Path(extension.bundled) if extension.bundled else None
    if source is not None:
        if not source.exists():
            raise ExtensionManagerError(
                f"{extension.id!r} is not shipped with this IngeTrazo.")
        archive_data = source.read_bytes() if source.is_file() else None
    else:
        archive_data = _get(extension.download, MAX_DOWNLOAD_BYTES)
        digest = hashlib.sha256(archive_data).hexdigest()
        if digest != extension.sha256:
            raise ExtensionManagerError(
                f"Checksum mismatch for {extension.id!r}; nothing was "
                "installed.")

    root = user_plugins_dir()
    root.mkdir(parents=True, exist_ok=True)
    keep_disabled = (target.is_dir()
                     and (target / ".disabled").is_file())
    stage = Path(tempfile.mkdtemp(prefix=f".{extension.id}-", dir=root))
    backup = root / f".{extension.id}-backup-{uuid.uuid4().hex}"
    try:
        if archive_data is None:            # a bundled package folder
            shutil.copytree(source, stage, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(
                                "__pycache__", "*.pyc"))
            is_zip = False
        else:
            is_zip = zipfile.is_zipfile(io.BytesIO(archive_data))
        if (urllib.parse.urlsplit(extension.download).path.lower().endswith(
                ".zip") and not is_zip):
            raise ExtensionManagerError(
                f"{extension.id!r} did not download a valid ZIP package.")
        if is_zip:
            _extract_plugin_zip(archive_data, stage, extension.id)
        elif archive_data is not None:
            if not archive_data or b"\x00" in archive_data:
                raise ExtensionManagerError(
                    f"{extension.id!r} is not a Python extension file.")
            (stage / "__init__.py").write_bytes(archive_data)
        copies = manual_copies(extension.id, stage, catalog_ids)
        if copies:
            if (confirm_manual_copies is None
                    or not confirm_manual_copies(copies)):
                raise ExtensionManagerError(
                    f"{extension.id!r} is already installed by hand in "
                    + ", ".join(p.name for p in copies)
                    + "; nothing was installed.")
            for path in copies:
                _set_aside(path)
        metadata = {
            "id": extension.id,
            "version": extension.version,
            "sha256": extension.sha256,
            "download": extension.download,
        }
        (stage / "extension.json").write_text(
            json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
        if keep_disabled:
            (stage / ".disabled").write_text("", encoding="utf-8")
        if target.exists():
            target.replace(backup)
        try:
            stage.replace(target)
        except OSError:
            if backup.exists() and not target.exists():
                backup.replace(target)
            raise
        if backup.exists():
            try:
                shutil.rmtree(backup)
            except OSError:
                logging.getLogger("ingetrazo.extensions").warning(
                    "could not remove replaced extension backup %s",
                    backup, exc_info=True)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage, ignore_errors=True)
        raise


def _extract_plugin_zip(data: bytes, stage: Path, ident: str) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except (OSError, zipfile.BadZipFile) as exc:
        raise ExtensionManagerError("The extension ZIP file is invalid.") from exc
    with archive:
        members = [info for info in archive.infolist()
                   if not info.is_dir()
                   and not info.filename.startswith("__MACOSX/")]
        if len(members) > MAX_ARCHIVE_FILES:
            raise ExtensionManagerError("The extension archive has too many files.")
        total_size = 0
        normalized = []
        for info in members:
            name = info.filename
            path = PurePosixPath(name)
            mode = info.external_attr >> 16
            # ":" never appears in a real package; on Windows «C:x» is a
            # drive-relative path and «a.py:s» an alternate data stream,
            # both of which can land outside the stage directory.
            if ("\\" in name or ":" in name or path.is_absolute()
                    or any(part in ("", ".", "..") for part in path.parts)
                    or stat.S_ISLNK(mode)):
                raise ExtensionManagerError(
                    "The extension archive contains an unsafe path.")
            total_size += info.file_size
            if total_size > MAX_EXTRACTED_BYTES:
                raise ExtensionManagerError(
                    "The unpacked extension is too large.")
            normalized.append((info, path))

        init_files = [(info, path) for info, path in normalized
                      if path.name == "__init__.py"]
        if init_files:
            min_depth = min(len(path.parent.parts) for _info, path in init_files)
            roots = {path.parent for _info, path in init_files
                     if len(path.parent.parts) == min_depth}
            if len(roots) > 1:
                matching = [root for root in roots if root.name == ident]
                if len(matching) != 1:
                    raise ExtensionManagerError(
                        "The ZIP contains multiple top-level plugin packages.")
                source_root = matching[0]
            else:
                source_root = next(iter(roots))
            selected = [(info, path) for info, path in normalized
                        if path.is_relative_to(source_root)]
            _copy_archive_members(archive, selected, source_root, stage)
            return

        modules = [(info, path) for info, path in normalized
                   if path.suffix == ".py"]
        primary = [(info, path) for info, path in modules
                   if path.name == f"{ident}.py"]
        if len(primary) != 1:
            raise ExtensionManagerError(
                "The ZIP must contain one plugin package or a Python file "
                f"named {ident}.py.")
        info, path = primary[0]
        source_root = path.parent
        selected = [(member, member_path) for member, member_path in normalized
                    if member_path.is_relative_to(source_root)]
        for member, member_path in selected:
            relative = member_path.relative_to(source_root)
            destination = stage / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(archive.read(member))
        (stage / path.name).replace(stage / "__init__.py")


def _copy_archive_members(archive, selected, source_root: PurePosixPath,
                          stage: Path) -> None:
    for info, path in selected:
        relative = path.relative_to(source_root)
        if not relative.parts:
            continue
        destination = stage.joinpath(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(archive.read(info))


def set_extension_enabled(ident: str, enabled: bool) -> None:
    target, managed = _managed_target(ident)
    if not managed or not target.is_dir():
        raise ExtensionManagerError(
            f"{ident!r} is not installed by the extension manager.")
    marker = target / ".disabled"
    if enabled:
        marker.unlink(missing_ok=True)
    else:
        marker.write_text("", encoding="utf-8")


def is_extension_enabled(ident: str) -> bool:
    target, managed = _managed_target(ident)
    return managed and target.is_dir() and not (target / ".disabled").exists()


def compatible_with_current(extension: Extension) -> bool:
    def parts(value):
        match = re.match(r"^\s*(\d+(?:\.\d+)*)", value)
        return tuple(map(int, match.group(1).split("."))) if match else None
    required, current = parts(extension.minimum_version), parts(__version__)
    if required is None or current is None:
        return False
    width = max(len(required), len(current))
    return required + (0,) * (width - len(required)) <= \
        current + (0,) * (width - len(current))


def tested_version_is_old(extension: Extension) -> bool:
    """True when tested metadata trails this app by two minor releases."""
    tested = re.match(r"^\s*(\d+)\.(\d+)", extension.minimum_version)
    current = re.match(r"^\s*(\d+)\.(\d+)", __version__)
    if not tested or not current:
        return False
    tested_major, tested_minor = map(int, tested.groups())
    current_major, current_minor = map(int, current.groups())
    return tested_major < current_major or (
        tested_major == current_major and current_minor - tested_minor >= 2)
