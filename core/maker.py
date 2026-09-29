# SPDX-License-Identifier: GPL-3.0-or-later
"""Parametric maker solids. Inputs and working meshes use millimetres.

Thread profile follows the user's SketchUp Thread Maker's truncated helical
profile. Gears use sampled involute flanks; NACA four-digit sections use the
analytic camber/thickness equations (closed trailing edge).
"""
import math

import manifold3d as m3d
import numpy as np
from PySide6.QtGui import QMatrix4x4, QVector3D

from core.group import Group
from core.mesh import Mesh


def _positive(**values):
    if any(not math.isfinite(v) or v <= 0 for v in values.values()):
        raise ValueError("Dimensions must be finite and greater than zero.")


def _group(solid, name):
    if solid.status() != m3d.Error.NoError or solid.is_empty():
        raise ValueError("These parameters did not produce a valid solid.")
    data = solid.to_mesh64()
    points = [QVector3D(*p[:3]) for p in data.vert_properties]
    mesh = Mesh()
    for triangle in data.tri_verts:
        mesh.add_face([points[int(i)] for i in triangle])
    # Hide triangulation diagonals and smooth close neighbouring facets.
    for edge in mesh.edges:
        if len(edge.faces) == 2:
            a, b = edge.faces
            if QVector3D.dotProduct(a.normal(), b.normal()) > .985:
                edge.soft = True
    group = Group(mesh, name)
    # Keep fine details above the mesh's 0.1 mm weld tolerance. Instance
    # transforms are honoured by placement, rendering, save and export.
    group.xform = QMatrix4x4()
    group.xform.scale(.001)
    return group


def _hex(across_flats):
    r = across_flats / math.sqrt(3)
    return [(r * math.cos(i * math.pi / 3), r * math.sin(i * math.pi / 3))
            for i in range(6)]


def _thread_solid(diameter, pitch, length, sides, left_hand):
    depth = .61343 * pitch
    root = diameter / 2 - depth
    if root <= 0:
        raise ValueError("Pitch is too large for the thread diameter.")
    layers = max(8, math.ceil(length / pitch * 12))
    if layers * sides > 60000:
        raise ValueError("Thread is too detailed; reduce length or quality, or increase pitch.")
    points, triangles = [], []
    for j in range(layers + 1):
        z = length * j / layers
        for i in range(sides):
            theta = 2 * math.pi * i / sides
            phase = (z / pitch - i / sides) % 1
            # Truncated root and crest, as in the reference Thread Maker.
            f = max(0., min(1., (phase - .08) / .37, (.92 - phase) / .37))
            r = diameter / 2 if j in (0, layers) else root + depth * f
            points.append((r * math.cos(theta), r * math.sin(theta), z))
    for j in range(layers):
        for i in range(sides):
            a, b = j * sides + i, j * sides + (i + 1) % sides
            c, d = b + sides, a + sides
            triangles.extend([(a, b, c), (a, c, d)])
    bottom, top = len(points), len(points) + 1
    points.extend([(0, 0, 0), (0, 0, length)])
    for i in range(sides):
        n = (i + 1) % sides
        triangles.extend([(bottom, n, i),
                          (top, layers * sides + i, layers * sides + n)])
    solid = m3d.Manifold(m3d.Mesh64(np.asarray(points, dtype=np.float64),
                                   np.asarray(triangles, dtype=np.uint64)))
    # Reflect the finished tessellation as well as the helix: keeping the
    # same diagonals while changing the phase gives a different volume.
    return solid.mirror((0, 1, 0)) if left_hand else solid


def thread(diameter=6., pitch=1., length=20., form="bolt", across_flats=10.,
           head_height=4., sides=48, left_hand=False, clearance=0.):
    """Threaded rod, hex-head bolt or internally threaded hex nut."""
    _positive(diameter=diameter, pitch=pitch, length=length)
    if not 12 <= sides <= 96 or int(sides) != sides:
        raise ValueError("Circle sides must be an integer from 12 to 96.")
    if not math.isfinite(clearance) or clearance < 0:
        raise ValueError("Nut radial clearance must be zero or positive.")
    if form not in ("bolt", "rod", "nut"):
        raise ValueError("Unknown thread form.")
    if form != "rod":
        _positive(across_flats=across_flats, head_height=head_height)
        if across_flats <= diameter + 2 * clearance:
            raise ValueError("Hex across-flats size must exceed the thread diameter and clearance.")
    if form == "nut":
        shell = m3d.CrossSection([_hex(across_flats)]).extrude(length)
        cutter = _thread_solid(diameter + 2 * clearance, pitch,
                               length + 2 * pitch, sides, left_hand).translate((0, 0, -pitch))
        solid = shell - cutter
    else:
        solid = _thread_solid(diameter, pitch, length, sides, left_hand)
        if form == "bolt":
            head = m3d.CrossSection([_hex(across_flats)]).extrude(head_height)
            solid = solid + head.translate((0, 0, -head_height))
    return _group(solid, f"{form.title()} M{diameter:g} x {pitch:g} x {length:g}")


def gear(teeth=24, module=1., thickness=5., bore=5., pressure_angle=20., samples=8):
    """External spur gear, zero profile shift, radial root transitions."""
    _positive(module=module, thickness=thickness)
    if int(teeth) != teeth or not 8 <= teeth <= 200:
        raise ValueError("Teeth must be an integer from 8 to 200.")
    if not 14.5 <= pressure_angle <= 30 or not 4 <= samples <= 24:
        raise ValueError("Pressure angle must be 14.5–30 degrees; quality 4–24.")
    angle = math.radians(pressure_angle)
    if teeth < math.ceil(2 / math.sin(angle) ** 2):
        raise ValueError("Too few teeth for this pressure angle without undercut. Increase teeth or pressure angle.")
    rp, ra, rf = module * teeth / 2, module * (teeth / 2 + 1), module * (teeth / 2 - 1.25)
    rb = rp * math.cos(angle)
    if not math.isfinite(bore) or not 0 <= bore < 2 * rf:
        raise ValueError("Bore must be smaller than the root diameter.")
    def involute(r):
        t = math.sqrt(max(0, (r / rb) ** 2 - 1))
        return t - math.atan(t)
    half = math.pi / (2 * teeth) + involute(rp)
    def polar(r, theta):
        return (r * math.cos(theta), r * math.sin(theta))
    profile = []
    start = max(rb, rf)
    for tooth in range(teeth):
        center = tooth * 2 * math.pi / teeth
        foot = half - involute(start)
        profile.append(polar(rf, center - foot))
        for k in range(samples + 1):
            r = start + (ra - start) * k / samples
            profile.append(polar(r, center - half + involute(r)))
        tip = half - involute(ra)
        for k in range(1, 5):
            profile.append(polar(ra, center - tip + 2 * tip * k / 4))
        for k in range(samples - 1, -1, -1):
            r = start + (ra - start) * k / samples
            profile.append(polar(r, center + half - involute(r)))
        profile.append(polar(rf, center + foot))
        end = center + 2 * math.pi / teeth - foot
        for k in range(1, 5):
            profile.append(polar(rf, center + foot + (end - center - foot) * k / 4))
    section = m3d.CrossSection([profile])
    if bore:
        section = section - m3d.CrossSection.circle(bore / 2, 64)
    return _group(section.extrude(thickness), f"Gear {teeth}T module {module:g}")


AEROFOIL_PRESETS = {
    "general": ("Wing — general purpose (NACA 2412)", "2412",
                "Moderately cambered wing section for a general starting point."),
    "high_lift": ("Wing — high lift (Selig S1223)", "s1223",
                  "High-lift low-Reynolds-number section. Strong camber and an undercambered lower surface; high lift does not imply a gentle stall."),
    "flat_bottom": ("Wing — flat lower surface (Clark Y)", "clarky",
                    "Classic wing section with a flat aft lower surface, useful for simple wing construction. The rounded nose is not flat."),
    "gentle_stall": ("Wing — slow-flight starting point (NACA 4415)", "4415",
                     "Cambered, 15%-thick section for exploring a slow-flight wing. A low stall speed requires suitable wing area and weight; gentle stall also depends on wing shape and washout."),
    "symmetric": ("Wing / tail — symmetric (NACA 0012)", "0012",
                  "Symmetric section for tails and symmetric wing designs."),
    "propeller": ("Propeller blade section (Eppler E850)", "e850",
                  "Section designed for propeller blades. Creates a straight section blank, not a finished propeller: blade twist, taper, hub and operating RPM still need design."),
}


def _stored_aerofoil(name, samples):
    """Resample the published contour by arc length without changing its frame."""
    from core.paths import app_root
    if name not in {"clarky", "s1223", "e850"}:
        raise ValueError("Unknown aerofoil profile.")
    path = app_root() / "resources" / "airfoils" / f"{name}.dat"
    points = np.loadtxt(path, skiprows=1)
    # Files use Selig order: upper TE -> nose -> lower TE. Retain the
    # original stations as well as extra samples so the supplied geometry
    # (especially the nose and flat underside) is not cut across.
    nose = int(np.argmin(points[:, 0]))
    pieces = []
    for side in (points[:nose+1], points[nose:]):
        lengths = np.r_[0., np.cumsum(np.linalg.norm(np.diff(side, axis=0), axis=1))]
        stations = np.unique(np.r_[lengths, np.linspace(0, lengths[-1], samples+1)])
        pieces.append(np.column_stack([np.interp(stations, lengths, side[:, i])
                                       for i in (0, 1)]))
    outline = np.vstack((pieces[0], pieces[1][1:]))
    if np.linalg.norm(outline[0] - outline[-1]) < 1e-8:
        outline = outline[:-1]
    return outline


def aerofoil(code="2412", chord=150., span=300., samples=60, preset="custom"):
    """Constant-section wing or blade blank, chord X, span Y, thickness Z."""
    _positive(chord=chord, span=span)
    if not 20 <= samples <= 160 or int(samples) != samples:
        raise ValueError("Profile samples must be an integer from 20 to 160.")
    if preset != "custom":
        if preset not in AEROFOIL_PRESETS:
            raise ValueError("Unknown aerofoil preset.")
        _, code, _ = AEROFOIL_PRESETS[preset]
        if not code.isdigit():
            outline = _stored_aerofoil(code, samples) * chord
            solid = m3d.CrossSection([outline]).extrude(span).rotate((90, 0, 0))
            return _group(solid, f"{code.upper()} — {chord:g} x {span:g} mm")
    if len(code) != 4 or not code.isascii() or not code.isdigit():
        raise ValueError("Enter a four-digit NACA code, for example 0012 or 2412.")
    m, p, t = int(code[0]) / 100, int(code[1]) / 10, int(code[2:]) / 100
    if not 0 < t <= .40 or (m and not 0 < p < 1) or (not m and p):
        raise ValueError("Invalid NACA camber/location or thickness (01–40%).")
    if not 20 <= samples <= 160 or int(samples) != samples:
        raise ValueError("Profile samples must be an integer from 20 to 160.")
    upper, lower = [], []
    for i in range(samples + 1):
        x = (1 - math.cos(math.pi * i / samples)) / 2
        yt = 5 * t * (.2969 * math.sqrt(x) - .1260 * x - .3516 * x*x
                      + .2843 * x**3 - .1036 * x**4)
        if not m:
            yc = slope = 0.
        elif x < p:
            yc, slope = m / p**2 * (2*p*x - x*x), 2*m / p**2 * (p-x)
        else:
            yc = m / (1-p)**2 * (1-2*p+2*p*x-x*x)
            slope = 2*m / (1-p)**2 * (p-x)
        theta = math.atan(slope)
        upper.append((chord*(x-yt*math.sin(theta)), chord*(yc+yt*math.cos(theta))))
        lower.append((chord*(x+yt*math.sin(theta)), chord*(yc-yt*math.cos(theta))))
    outline = list(reversed(upper)) + lower[1:-1]
    solid = m3d.CrossSection([outline]).extrude(span).rotate((90, 0, 0))
    return _group(solid, f"NACA {code} — {chord:g} x {span:g} mm")
