# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Runs INSIDE Blender (``blender -b --factory-startup --python
render_scene.py -- job.json``): IngeTrazo's side of "Render with Blender"
(issue #181, plugins/render_blender.py).

The job file says everything: the GLB IngeTrazo exported, its camera, the
sun, the engine and quality, and where to write the image (and, if asked,
the .blend). Blender's glTF importer turns glTF's Y-up back into Z-up, so
the model lands in IngeTrazo's own coordinates and the camera goes in as
given.

Written against Blender 3.6–5.x: every name that changed between versions
(the EEVEE engine id, the physical sky) is tried in turn, and anything a
version lacks degrades to something plainer instead of failing the render.
Progress goes to stdout as ``INGETRAZO <what>`` lines the dialog reads.

With ``"serve": true`` in the job it renders nothing at first: it builds
the scene once, says ``INGETRAZO ready`` and then reads one JSON request per
line on stdin — ``{"camera": …, "output": …, "width": …, "height": …,
"samples": …}`` → renders it and says ``INGETRAZO done <output>``;
``{"quit": true}`` or the end of stdin stops it. That is Render ▸ «Sync
with the view»: only the camera travels, and the face-me figures (glTF
nodes with ``ingetrazo_faceme`` = feet + heading in their extras) are turned
toward each new camera instead of exporting the model again.
"""
import json
import math
import sys

import bpy
from mathutils import Matrix, Vector


def say(*parts):
    print("INGETRAZO", *parts, flush=True)


def load_job():
    argv = sys.argv
    if "--" not in argv:
        raise SystemExit("render_scene.py: no job file after '--'")
    with open(argv[argv.index("--") + 1], encoding="utf-8") as fh:
        return json.load(fh)


def import_model(path):
    bpy.ops.import_scene.gltf(filepath=path)
    objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
    part_two_sided_faces({o.data for o in objs})
    say("imported", len(objs), "objects")
    return objs


def part_two_sided_faces(meshes, gap=1e-4):
    """A face painted on both sides comes as two single-sided copies in the
    same plane (formats/meshexport.py). Cycles culls no back face, so it
    showed either one, triangle by triangle (#1569): each copy steps a
    tenth of a millimetre out to its own side."""
    for mesh in meshes:
        single = {i for i, mat in enumerate(mesh.materials)
                  if mat is not None and mat.use_backface_culling}
        out = {}
        for poly in mesh.polygons if single else ():
            if poly.material_index in single:
                for v in poly.vertices:
                    out[v] = out.get(v, Vector()) + poly.normal
        for v, normal in out.items():
            if normal.length > 1e-6:
                mesh.vertices[v].co += normal.normalized() * gap


def _set(bsdf, names, value):
    """Set the first of ``names`` this Blender's Principled BSDF has
    (inputs were renamed in 4.0: Transmission → Transmission Weight…)."""
    for n in names:
        sock = bsdf.inputs.get(n)
        if sock is not None:
            try:
                sock.default_value = value
            except (TypeError, ValueError):
                continue
            for link in list(sock.links):      # a fixed value, not a map
                sock.id_data.links.remove(link)
            return True
    return False


def _ripples(mat, bsdf, scale=6.0, strength=0.12):
    """Small waves for water: noise → bump → the BSDF's normal."""
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    if "Detail" in noise.inputs:
        noise.inputs["Detail"].default_value = 6.0
    bump = nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = strength
    if "Distance" in bump.inputs:
        bump.inputs["Distance"].default_value = 0.02
    links.new(noise.outputs["Fac"], bump.inputs["Height"])
    links.new(bump.outputs["Normal"], bsdf.inputs["Normal"])


def apply_finishes():
    """Turn IngeTrazo's finish (glTF extras, core.finish) into a real
    material: the importer keeps extras as custom properties."""
    counts = {}
    for mat in bpy.data.materials:
        finish = mat.get("ingetrazo_finish")
        if not finish or not mat.node_tree:
            continue
        bsdf = next((n for n in mat.node_tree.nodes
                     if n.type == "BSDF_PRINCIPLED"), None)
        if bsdf is None:
            continue
        counts[finish] = counts.get(finish, 0) + 1
        spec = ("Specular IOR Level", "Specular")
        if finish == "matte":
            _set(bsdf, ("Roughness",), 0.9)
            _set(bsdf, spec, 0.3)
        elif finish == "satin":
            _set(bsdf, ("Roughness",), 0.45)
        elif finish == "gloss":
            _set(bsdf, ("Roughness",), 0.1)
            _set(bsdf, ("Coat Weight", "Clearcoat"), 0.5)
            _set(bsdf, ("Coat Roughness", "Clearcoat Roughness"), 0.03)
        elif finish == "metal":
            _set(bsdf, ("Metallic",), 1.0)
            _set(bsdf, ("Roughness",), 0.28)
        elif finish in ("glass", "water"):
            glass = finish == "glass"
            _set(bsdf, ("Roughness",), 0.0 if glass else 0.02)
            _set(bsdf, ("IOR",), 1.45 if glass else 1.33)
            _set(bsdf, spec, 1.0)
            if glass:
                # Real refraction instead of a see-through alpha.
                _set(bsdf, ("Transmission Weight", "Transmission"), 1.0)
                _set(bsdf, ("Alpha",), 1.0)
                for attr, value in (("blend_method", "OPAQUE"),
                                    ("use_raytrace_refraction", True),
                                    ("use_screen_refraction", True)):
                    if hasattr(mat, attr):
                        try:
                            setattr(mat, attr, value)
                        except (TypeError, ValueError):
                            pass
            else:
                _ripples(mat, bsdf)
    if counts:
        say("finishes", ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))


def set_camera(scene, cam_cfg, width, height):
    cam = scene.camera
    if cam is None or cam.name != "IngeTrazo camera":
        data = bpy.data.cameras.new("IngeTrazo")
        cam = bpy.data.objects.new("IngeTrazo camera", data)
        scene.collection.objects.link(cam)
        scene.camera = cam
    data = cam.data
    eye = Vector(cam_cfg["eye"])
    target = Vector(cam_cfg["target"])
    up = Vector(cam_cfg["up"])
    fwd = (target - eye).normalized()
    right = fwd.cross(up)
    if right.length < 1e-9:                    # looking straight along "up"
        right = fwd.cross(Vector((0.0, 1.0, 0.0)))
    right.normalize()
    true_up = right.cross(fwd).normalized()
    # A Blender camera looks down its local -Z with +Y up.
    rot = Matrix((right, true_up, -fwd)).transposed()
    cam.matrix_world = Matrix.Translation(eye) @ rot.to_4x4()
    data.sensor_fit = "VERTICAL"
    if cam_cfg.get("perspective", True):
        data.type = "PERSP"
        data.angle_y = math.radians(cam_cfg["fov_deg"])
    else:
        data.type = "ORTHO"
        data.ortho_scale = 2.0 * cam_cfg["half_height"] * max(
            1.0, width / max(height, 1))
    data.clip_start = max(cam_cfg.get("near", 0.05), 1e-4)
    data.clip_end = max(cam_cfg.get("far", 1e5), data.clip_start * 10)
    return cam


def find_figures():
    """The face-me figures: ``(object, feet, heading, matrix as imported)``."""
    out = []
    for obj in bpy.context.scene.objects:
        tag = obj.get("ingetrazo_faceme")
        if tag is None:
            continue
        try:
            fx, fy, fz, yaw = (float(v) for v in tag)
        except (TypeError, ValueError):
            continue
        out.append((obj, Vector((fx, fy, fz)), yaw, obj.matrix_world.copy()))
    if out:
        say("figures", len(out))
    return out


def face_figures(figures, cam_cfg):
    """Turn each figure about the vertical through its feet to face the
    camera — as the viewport does: toward the eye in perspective, along the
    view in a parallel projection."""
    eye = Vector(cam_cfg["eye"])
    target = Vector(cam_cfg["target"])
    for obj, feet, yaw0, base in figures:
        d = (eye - feet) if cam_cfg.get("perspective", True) else (eye - target)
        if math.hypot(d.x, d.y) < 1e-9:
            continue
        turn = math.atan2(d.y, d.x) - yaw0
        obj.matrix_world = (Matrix.Translation(feet)
                            @ Matrix.Rotation(turn, 4, "Z")
                            @ Matrix.Translation(-feet) @ base)


def add_sun(scene, direction, strength):
    """``direction`` points FROM the scene TOWARD the sun (core.sun)."""
    d = Vector(direction).normalized()
    light = bpy.data.lights.new("IngeTrazo sun", type="SUN")
    light.energy = strength
    light.angle = math.radians(0.53)           # the real sun's disc
    sun = bpy.data.objects.new("IngeTrazo sun", light)
    scene.collection.objects.link(sun)
    # A sun light shines along its local -Z: point +Z at the sun.
    sun.rotation_euler = d.to_track_quat("Z", "Y").to_euler()
    return sun


def set_world(scene, sun_dir):
    world = bpy.data.worlds.new("IngeTrazo sky")
    scene.world = world
    if hasattr(world, "use_nodes"):            # gone in Blender 6: always on
        world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    bg = nodes.get("Background") or nodes.new("ShaderNodeBackground")
    sky = nodes.new("ShaderNodeTexSky")
    chosen = None
    for kind in ("MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING",
                 "HOSEK_WILKIE", "PREETHAM"):
        try:
            sky.sky_type = kind
            chosen = kind
            break
        except (TypeError, ValueError):
            continue
    if sun_dir is not None:
        d = Vector(sun_dir).normalized()
        elevation = math.asin(max(-1.0, min(1.0, d.z)))
        rotation = math.atan2(d.x, d.y)            # from +Y (north), clockwise
        for attr, value in (("sun_elevation", elevation),
                            ("sun_rotation", -rotation + math.pi / 2)):
            if hasattr(sky, attr):
                setattr(sky, attr, value)
        if hasattr(sky, "sun_direction"):
            sky.sun_direction = d
        if hasattr(sky, "sun_disc"):
            sky.sun_disc = False                   # the Sun lamp is the sun
    links.new(sky.outputs["Color"], bg.inputs["Color"])
    # The physical skies are bright; Preetham/Hosek are dim.
    bg.inputs["Strength"].default_value = (
        0.12 if chosen in ("MULTIPLE_SCATTERING", "NISHITA",
                           "SINGLE_SCATTERING") else 0.6)
    say("sky", chosen)


def set_plain_world(scene, color, strength, name):
    """A sky of one colour: the dark blue of a night, the grey of an
    overcast day (the whole sky lights the scene evenly)."""
    world = bpy.data.worlds.new(f"IngeTrazo {name}")
    scene.world = world
    if hasattr(world, "use_nodes"):
        world.use_nodes = True
    bg = (world.node_tree.nodes.get("Background")
          or world.node_tree.nodes.new("ShaderNodeBackground"))
    bg.inputs["Color"].default_value = (*color, 1.0)
    bg.inputs["Strength"].default_value = strength
    say("sky", name)


def add_moon(scene):
    """A faint cold key light from high up, so a night still has shape."""
    light = bpy.data.lights.new("IngeTrazo moon", type="SUN")
    light.energy = 0.08
    light.color = (0.7, 0.8, 1.0)
    light.angle = math.radians(1.0)
    moon = bpy.data.objects.new("IngeTrazo moon", light)
    scene.collection.objects.link(moon)
    moon.rotation_euler = Vector((0.3, -0.4, 0.86)).normalized().to_track_quat(
        "Z", "Y").to_euler()


def add_lights(scene, lights):
    """The lights placed in IngeTrazo's Render panel: point lights (a bulb,
    a lantern) and spots (a lamp post head, a reflector) in real watts."""
    for i, lt in enumerate(lights):
        kind = "SPOT" if lt["kind"] == "spot" else "POINT"
        data = bpy.data.lights.new(f"IngeTrazo light {i + 1}", type=kind)
        data.energy = float(lt["power"])
        data.color = tuple(lt["color"])
        if hasattr(data, "shadow_soft_size"):
            data.shadow_soft_size = 0.08          # a lamp, not a point
        if kind == "SPOT":
            data.spot_size = math.radians(float(lt["angle"]))
            data.spot_blend = 0.35
        obj = bpy.data.objects.new(lt.get("name") or data.name, data)
        scene.collection.objects.link(obj)
        obj.location = Vector(lt["pos"])
        if kind == "SPOT":
            # A spot shines along its local -Z.
            d = Vector(lt["dir"]).normalized()
            obj.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    if lights:
        say("lights", len(lights))


def add_ground(scene, z, size, color):
    bpy.ops.mesh.primitive_plane_add(size=size, location=(0.0, 0.0, z))
    ground = bpy.context.active_object
    ground.name = "IngeTrazo ground"
    mat = bpy.data.materials.new("IngeTrazo ground")
    if hasattr(mat, "use_nodes"):
        mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Roughness"].default_value = 0.9
    ground.data.materials.append(mat)


def set_samples(scene, samples):
    if scene.render.engine == "CYCLES":
        scene.cycles.samples = samples
    elif hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = samples


def set_engine(scene, engine, samples):
    if engine == "cycles":
        scene.render.engine = "CYCLES"
        scene.cycles.samples = samples
        scene.cycles.use_denoising = True
        try:                                   # use the GPU when there is one
            prefs = bpy.context.preferences.addons["cycles"].preferences
            for backend in ("OPTIX", "CUDA", "HIP", "METAL", "ONEAPI"):
                try:
                    prefs.compute_device_type = backend
                except TypeError:
                    continue
                prefs.get_devices()
                # prefs.devices lists every backend's devices: count only
                # this one's (with CUDA chosen, an AMD card shows as HIP).
                gpus = [d for d in prefs.devices if d.type == backend]
                if gpus:
                    for d in prefs.devices:
                        d.use = d.type in (backend, "CPU")
                    scene.cycles.device = "GPU"
                    say("device", backend)
                    break
        except Exception:                      # noqa: BLE001 — CPU is fine
            pass
    else:
        for name in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
            try:
                scene.render.engine = name
                break
            except TypeError:
                continue
        set_samples(scene, samples)
        eevee = scene.eevee
        for flag in ("use_shadows", "use_raytracing", "use_gtao",
                     "use_ssr", "use_ssr_refraction"):
            if hasattr(eevee, flag):
                setattr(eevee, flag, True)
    say("engine", scene.render.engine)


def main():
    job = load_job()
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    import_model(job["glb"])
    apply_finishes()
    figures = find_figures()
    w, h = int(job["width"]), int(job["height"])
    set_camera(scene, job["camera"], w, h)
    face_figures(figures, job["camera"])
    ambience = job.get("ambience", "day")
    sun_dir = job.get("sun") if ambience == "day" else None
    if ambience == "night":
        set_plain_world(scene, (0.010, 0.016, 0.035), 1.0, "night")
        add_moon(scene)
    elif ambience == "overcast":
        set_plain_world(scene, (0.62, 0.66, 0.70), 1.0, "overcast")
    else:
        if sun_dir is not None:
            add_sun(scene, sun_dir, float(job.get("sun_strength", 4.0)))
        set_world(scene, sun_dir)
    add_lights(scene, job.get("lights") or [])
    ground = job.get("ground")
    if ground:
        add_ground(scene, ground["z"], ground["size"], ground["color"])
    set_engine(scene, job.get("engine", "eevee"), int(job.get("samples", 64)))
    r = scene.render
    r.resolution_x, r.resolution_y, r.resolution_percentage = w, h, 100
    r.image_settings.file_format = "PNG"
    r.filepath = job["output"]
    r.film_transparent = False
    # A daylit scene under AgX washes out at exposure 0: step it down and
    # take the punchier look when this Blender has it.
    view = scene.view_settings
    view.exposure = float(job.get("exposure", -0.6))
    for look in ("AgX - Medium High Contrast", "Medium High Contrast",
                 "AgX - Punchy", "Punchy"):
        try:
            view.look = look
            break
        except TypeError:
            continue
    # Blender 5 no longer prints per-sample progress in the background;
    # the stats handler still hears it («… | Sample 12/128» in Cycles,
    # «Rendering 12 / 64 samples» in EEVEE). Forward it for the dialog.
    last = {"text": None}

    def _stats(text, *_a):
        text = str(text)
        if text != last["text"]:
            last["text"] = text
            say("stats", text.replace("\n", " "))

    if hasattr(bpy.app.handlers, "render_stats"):
        bpy.app.handlers.render_stats.append(_stats)
    if job.get("serve"):
        serve(scene, figures)
        return
    say("rendering", w, "x", h)
    bpy.ops.render.render(write_still=True)
    if job.get("blend"):
        bpy.ops.wm.save_as_mainfile(filepath=job["blend"])
        say("blend", job["blend"])
    say("done", job["output"])



def serve(scene, figures):
    """Render each camera IngeTrazo sends until told to stop."""
    say("ready")
    r = scene.render
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except ValueError:
            say("error", "bad request")
            continue
        if req.get("quit"):
            break
        w, h = int(req["width"]), int(req["height"])
        set_camera(scene, req["camera"], w, h)
        face_figures(figures, req["camera"])
        set_samples(scene, int(req.get("samples", 16)))
        r.resolution_x, r.resolution_y = w, h
        r.filepath = req["output"]
        say("rendering", w, "x", h)
        bpy.ops.render.render(write_still=True)
        say("done", req["output"])


main()
