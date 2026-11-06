# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 IngeTrazo contributors.
"""Stage and independently validate a delivery before atomically publishing it."""
from __future__ import annotations

import hashlib
import html
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
import zipfile

from core.delivery_workflow import evaluate, filename, model_fingerprint


def digest(path):
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_pdfa(path, validator):
    """Use a configured veraPDF CLI JAR/executable, never a shell command."""
    validator = Path(validator)
    if not validator.is_file() or validator.suffix.lower() in (".bat", ".cmd"):
        raise ValueError("Select the veraPDF CLI JAR or executable")
    if validator.suffix.lower() == ".jar":
        java = shutil.which("java")
        if not java:
            raise ValueError("Java is required for the selected veraPDF JAR")
        command = [java, "-jar", str(validator)]
    else:
        command = [str(validator)]
    process = subprocess.run(command + ["--format", "xml", "--flavour", "1b", str(Path(path).resolve())],
                             capture_output=True, text=True, encoding="utf-8", errors="replace",
                             timeout=180, shell=False,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        root = ET.fromstring(process.stdout)
        records = [node for node in root.iter() if node.tag.rsplit("}", 1)[-1] == "validationReport"]
    except ET.ParseError as exc:
        raise ValueError("veraPDF did not return a usable XML report") from exc
    passed = bool(records) and all(n.get("isCompliant") == "true" for n in records)
    if not passed or process.returncode not in (0,):
        raise ValueError("PDF/A-1b validation failed: " + process.stdout[-3500:])
    return {"sha256": digest(path), "verified": True, "profile": "PDF/A-1b",
            "validator": "veraPDF", "xml": process.stdout}


def validate_ifc(path):
    try:
        import ifcopenshell
        import ifcopenshell.validate
    except ImportError as exc:
        raise ValueError("Install the optional IfcOpenShell delivery validator") from exc
    model = ifcopenshell.open(str(path))
    if model.schema_identifier != "IFC4X3_ADD2":
        raise ValueError("Delivery IFC must use IFC4X3_ADD2")
    log = ifcopenshell.validate.json_logger()
    ifcopenshell.validate.validate(model, log, express_rules=True)
    if log.statements:
        raise ValueError(json.dumps(log.statements, default=str, ensure_ascii=False))
    return {"validator": "IfcOpenShell", "version": ifcopenshell.version,
            "sha256": digest(path), "schema": model.schema_identifier, "findings": []}


def quality_html(report):
    escape = lambda text: html.escape(str(text))
    rows = "".join("<tr>" + "".join(f"<td>{escape({'pass': 'Geçti', 'fail': 'Kaldı', 'pending': 'Bekliyor'}.get(row[key], row[key]) if key == 'status' else row[key])}</td>" for key in
        ("number", "label", "status", "reviewer", "review_date", "evidence")) + "</tr>"
        for row in report["checks"])
    issues = "".join("<li>" + escape(i) + "</li>" for i in report.get("issues", []))
    return ("<!doctype html><html lang='tr'><meta charset='utf-8'><title>Model kalite kontrolü</title>"
            "<style>body{font:14px sans-serif;margin:32px}table{border-collapse:collapse;width:100%}"
            "td,th{border:1px solid #aaa;padding:8px;text-align:left}h1{font-size:24px}</style>"
            "<h1>Model kalite kontrol formu — EK-9</h1><p>Model: " +
            escape(report["model_fingerprint"]) + "</p><ul>" + issues + "</ul><table><thead><tr><th>No</th><th>Kontrol</th>"
            "<th>Sonuç</th><th>Kontrol eden</th><th>Tarih</th><th>Kanıt</th></tr></thead><tbody>" +
            rows + "</tbody></table><p>Otomatik kontroller ve adı belirtilen kişinin inceleme kayıtları."
            " Elektronik imza yerine geçmez.</p></html>")


def build_package(window, destination, *, pdf_exporter=None, pdf_validator=None):
    """Only a fully checked package replaces destination; failure keeps it intact.

    Test seams supply independent exporters/validators; production uses the
    existing vector sheet renderer and veraPDF. No review answers are filled here.
    """
    from core.bim import collect_objects
    from core.turkiye_delivery import object_issues, rules
    from core.delivery_workflow import project_issues
    from formats import ifc, igz
    scene = window.viewport.scene
    window.viewport.end_group_edit()
    project = scene.ifc_project
    if project.get("delivery_version") != 2:
        raise ValueError("Complete the project/delivery workflow first")
    objects = collect_objects(scene)
    problems = project_issues(scene, objects)
    for obj in objects:
        problems.extend(object_issues(obj))
    if problems:
        raise ValueError(json.dumps(problems, ensure_ascii=False))
    if not scene.compositions or any(not c.frames for c in scene.compositions):
        raise ValueError("Delivery requires model-linked sheets")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fingerprint = model_fingerprint(scene)
    composer = None
    if pdf_exporter is None:
        from views.composer import ComposerWindow
        composer = ComposerWindow(window)
        def pdf_exporter(comp, path):
            composer.comp = comp
            composer.export_pdf(str(path), archival=True)
    pdf_validator = pdf_validator or (lambda path: validate_pdfa(path, project.get("validator", "")))
    try:
        with tempfile.TemporaryDirectory(prefix=".ingetrazo-delivery-", dir=destination.parent) as folder:
            folder = Path(folder)
            model = folder / filename(project)
            ifc.save_ifc(scene, model, schema="IFC4X3_ADD2")
            schema = validate_ifc(model)
            pdfs = []
            names = {model.name}
            for index, comp in enumerate(scene.compositions, 1):
                overrides = {"kind": "PL", "sequence": f"{index:02d}"}
                overrides.update(project.get("sheet_filenames", {}).get(comp.name, {}))
                name = filename(project, "pdf", overrides)
                if name in names:
                    raise ValueError("Duplicate delivery document filename")
                names.add(name)
                target = folder / name
                pdf_exporter(comp, target)
                if target.stat().st_size > project["filename"]["max_size_mb"] * 1024 * 1024:
                    raise ValueError("Sheet exceeds the entered delivery file-size limit: " + name)
                result = pdf_validator(target)
                if not result.get("verified") or result.get("sha256") != digest(target):
                    raise ValueError("PDF/A validation evidence does not match the file")
                (folder / (name + ".verapdf.xml")).write_text(result.pop("xml", ""), encoding="utf-8")
                pdfs.append({**result, "file": name, "sheet": comp.name,
                             "model_fingerprint": fingerprint})
            if fingerprint != model_fingerprint(scene):
                raise ValueError("Model changed during delivery generation; retry")
            report = evaluate(scene, {"issues": []}, file_size=model.stat().st_size,
                              pdfs=pdfs, schema_evidence=schema)
            if not report["release_ready"]:
                # A reviewable diagnostic survives, but never a green package.
                diagnostic = destination.with_suffix(".checks.json")
                diagnostic.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
                raise ValueError("Delivery blocked: review the failed/pending EK-9 rows in " + str(diagnostic))
            igz.save_scene(scene, folder / filename(project, "igz"))
            (folder / "quality.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            (folder / "quality.html").write_text(quality_html(report), encoding="utf-8")
            from formats.pdfa import write_quality_pdf
            quality_path = folder / "quality.pdf"
            write_quality_pdf(quality_html(report), quality_path)
            quality_proof = pdf_validator(quality_path)
            if not quality_proof.get("verified") or quality_proof.get("sha256") != digest(quality_path):
                raise ValueError("Quality form PDF/A evidence does not match")
            (folder / "quality.pdf.verapdf.xml").write_text(quality_proof.pop("xml", ""), encoding="utf-8")
            manifest = {"format": 1, "model_fingerprint": fingerprint, "ifc": schema,
                        "pdfs": pdfs, "source_edition": "RG 2026-08-05/33331",
                        "quality_pdf": quality_proof,
                        "source": rules()["source"],
                        "files": {p.name: digest(p) for p in folder.iterdir() if p.is_file()}}
            (folder / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            pending = folder / "package.zip"
            with zipfile.ZipFile(pending, "w", zipfile.ZIP_DEFLATED) as archive:
                for item in sorted(folder.iterdir()):
                    if item != pending:
                        archive.write(item, item.name)
            os.replace(pending, destination)
            return manifest
    finally:
        if composer is not None:
            composer.close()
