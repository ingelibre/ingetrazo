# SPDX-License-Identifier: GPL-3.0-or-later
"""OpenCFD OpenFOAM v2312 steady external-flow case exporter (SI units).

No solver is embedded. Cases are exploratory until independently validated.
"""
from dataclasses import dataclass, asdict
from pathlib import Path
from collections import Counter
import json
import math
import struct
import tempfile
import shutil
import numpy as np
from PySide6.QtGui import QVector3D
from core.group import iter_placements, np_affine

IMAGE = 'opencfd/openfoam-default:2312'
STAGES = [('blockMesh', []), ('surfaceFeatureExtract', []),
          ('snappyHexMesh', ['-overwrite']), ('checkMesh', ['-allTopology', '-allGeometry']),
          ('simpleFoam', [])]


@dataclass
class Settings:
    mode: str = 'aircraft'
    speed: float = 15.
    heading: float = 0.       # flow TOWARDS, counterclockwise from model +X
    alpha: float = 0.
    density: float = 1.225
    viscosity: float = 1.5e-5
    intensity: float = .01
    reference_area: float = 1.
    reference_length: float = 1.
    roughness: float = .03
    reference_height: float = 10.
    resolution: int = 4
    iterations: int = 500

    def validate(self):
        if self.mode not in ('aircraft', 'terrain'):
            raise ValueError('Choose aircraft or terrain mode.')
        for key, value in asdict(self).items():
            if key != 'mode' and not math.isfinite(value):
                raise ValueError(f'{key} must be finite.')
        for key in ('speed', 'density', 'viscosity', 'reference_area', 'reference_length',
                    'roughness', 'reference_height'):
            if getattr(self, key) <= 0:
                raise ValueError(f'{key} must be greater than zero.')
        if not 0 < self.intensity <= .5 or not 4 <= self.resolution <= 12:
            raise ValueError('Turbulence intensity must be 0–50%; mesh resolution 4–12.')
        if int(self.resolution) != self.resolution or int(self.iterations) != self.iterations or not 10 <= self.iterations <= 10000:
            raise ValueError('Use integer resolution and 10–10000 iterations.')
        if self.mode == 'terrain' and self.alpha != 0:
            raise ValueError('Terrain wind must be horizontal (angle of attack = 0).')


def frame(settings):
    """World vectors to wind frame; inlet always +X, terrain retains vertical."""
    yaw, pitch = np.radians([-settings.heading, settings.alpha])
    c, s = math.cos(yaw), math.sin(yaw)
    rz = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1.]])
    c, s = math.cos(pitch), math.sin(pitch)
    return np.array([[c, 0, s], [0, 1., 0], [-s, 0, c]]) @ rz


def validate_surface(triangles):
    """Reject holes, nonmanifold edges, inconsistent normals and collapsed faces."""
    tri = np.asarray(triangles, dtype=float)
    if tri.ndim != 3 or tri.shape[1:] != (3, 3) or not len(tri):
        raise ValueError('No surface triangles were found.')
    if not np.isfinite(tri).all():
        raise ValueError('Geometry contains non-finite coordinates.')
    scale = float(np.ptp(tri.reshape(-1, 3), axis=0).max())
    if scale <= 1e-8:
        raise ValueError('Geometry is too small or collapsed.')
    if np.any(np.linalg.norm(np.cross(tri[:, 1]-tri[:, 0], tri[:, 2]-tri[:, 0]), axis=1) < scale*scale*1e-14):
        raise ValueError('Geometry has degenerate triangles. Repair it before meshing.')
    edges, direction = Counter(), Counter()
    origin = tri.reshape(-1, 3).min(axis=0)
    quantized = np.rint((tri-origin)/(scale*1e-9)).astype(np.int64)
    for face in quantized:
        verts = [tuple(p) for p in face]
        for a, b in zip(verts, verts[1:]+verts[:1]):
            edge = tuple(sorted((a, b)))
            edges[edge] += 1
            direction[edge] += 1 if a < b else -1
    if any(n != 2 for n in edges.values()):
        raise ValueError('Surface is not watertight: every edge must have two faces. Repair holes or overlapping faces.')
    if any(direction.values()):
        raise ValueError('Surface face directions are inconsistent. Orient the solid faces outward.')
    return tri


def group_triangles(groups):
    result = []
    for group in groups:
        pieces = []
        # Transform triangles directly: rebuilding a world Mesh would weld
        # small aerofoil details at the CAD model's editing tolerance.
        for placement, transform in iter_placements(group):
            local = np.array([[[p.x(), p.y(), p.z()] for p in t]
                              for f in placement.mesh.faces if not f.interior
                              for t in f.triangulate()], dtype=float)
            if not len(local):
                continue
            if transform is not None:
                rotation, translation = np_affine(transform)
                local = local @ rotation.T + translation
                if np.linalg.det(rotation) < 0:
                    local = local[:, ::-1]
            pieces.append(local)
        tri = np.concatenate(pieces) if pieces else []
        try:
            valid = validate_surface(tri)
        except ValueError as exc:
            raise ValueError(f'{group.name}: {exc}') from exc
        result.append(valid)
    if not result:
        raise ValueError('Select at least one closed solid group for the aircraft or obstacles.')
    return np.concatenate(result)


def vec(values):
    return '(' + ' '.join(f'{float(v):.10g}' for v in values) + ')'


def header(name, cls='dictionary'):
    return f'FoamFile\n{{ version 2.0; format ascii; class {cls}; object {name}; }}\n\n'


def write_stl(path, triangles):
    with Path(path).open('wb') as stream:
        stream.write(b'IngeTrazo CFD surface; metres'.ljust(80, b'\0'))
        stream.write(struct.pack('<I', len(triangles)))
        for a, b, c in triangles:
            n = np.cross(b-a, c-a); n /= np.linalg.norm(n)
            stream.write(struct.pack('<12fH', *n, *a, *b, *c, 0))


def terrain_solid(terrain, rotation, centre, domain, ground_z):
    """Extend DEM edge heights beyond domain, close sides/base below fluid.

    Only sampled terrain is observational data; extension is explicitly reported.
    """
    low, high = domain
    length = max(high-low)
    xs = np.linspace(low[0]-.02*length, high[0]+.02*length, min(181, max(41, terrain.nx)))
    ys = np.linspace(low[1]-.02*length, high[1]+.02*length, min(181, max(41, terrain.ny)))
    points = []
    xmin, ymin, xmax, ymax = terrain.bbox
    for y in ys:
        for x in xs:
            world = rotation.T @ np.array([x, y, 0.]) + centre
            z = terrain.height_at(float(np.clip(world[0], xmin, xmax)), float(np.clip(world[1], ymin, ymax)))
            if z is None or not math.isfinite(z):
                raise ValueError('Terrain grid has missing heights.')
            points.append([x, y, z-ground_z])
    points = np.asarray(points)
    nx, ny = len(xs), len(ys)
    faces = []
    for j in range(ny-1):
        for i in range(nx-1):
            a = j*nx+i
            faces.extend([(a, a+1, a+nx), (a+1, a+nx+1, a+nx)])
    boundary = (list(range(nx)) + [j*nx+nx-1 for j in range(1, ny)] +
                list(range(nx*ny-2, nx*(ny-1)-1, -1)) +
                [j*nx for j in range(ny-2, 0, -1)])
    bottom = low[2] - length
    extras = [[*points[index][:2], bottom] for index in boundary]
    offset = len(points)
    points = np.vstack([points, extras, [[0, 0, bottom]]])
    central = len(points)-1
    for k, a in enumerate(boundary):
        n = (k+1) % len(boundary); b = boundary[n]
        faces.extend([(a, offset+k, offset+n), (a, offset+n, b),
                      (central, offset+n, offset+k)])
    return validate_surface(points[np.asarray(faces)])


def generate_case(destination, groups, settings, terrain=None):
    """Create an entirely new case, atomically. Never overwrite prior results."""
    settings.validate()
    groups = list(groups)
    destination = Path(destination).expanduser().resolve()
    if destination.exists():
        raise ValueError('Choose a new case folder; existing cases are never overwritten.')
    rotation = frame(settings)
    obstacles = group_triangles(groups) if groups else None
    if settings.mode == 'aircraft' and obstacles is None:
        raise ValueError('Select closed aircraft groups first.')
    if settings.mode == 'terrain':
        if terrain is None or terrain.nx < 2 or terrain.ny < 2:
            raise ValueError('Load a 3D terrain grid first (flat map imagery has no heights).')
        vertices = np.array([[p.x(), p.y(), p.z()] for p in terrain.vertices])
        if not np.isfinite(vertices).all():
            raise ValueError('Terrain contains missing heights.')
    else:
        vertices = obstacles.reshape(-1, 3)
    centre = (vertices.min(axis=0)+vertices.max(axis=0))/2
    if settings.mode == 'terrain':
        centre[2] = vertices[:, 2].min()
    transformed = (vertices-centre) @ rotation.T
    lo, hi = transformed.min(axis=0), transformed.max(axis=0)
    length = float(max(hi-lo))
    if length <= 1e-6:
        raise ValueError('Model has no usable extent.')
    if settings.mode == 'aircraft':
        low, high = lo - np.array([5, 5, 5])*length, hi + np.array([10, 5, 5])*length
    else:
        low = np.array([lo[0]-length, lo[1]-.5*length, -.25*length])
        high = np.array([hi[0]+2*length, hi[1]+.5*length, max(hi[2]+length, settings.reference_height*3)])
    if obstacles is not None:
        obstacles = (obstacles-centre) @ rotation.T
        if settings.mode == 'terrain' and (np.any(obstacles.reshape(-1, 3).min(axis=0) < low) or np.any(obstacles.reshape(-1, 3).max(axis=0) > high)):
            raise ValueError('An obstacle lies outside the terrain domain. Select only nearby buildings.')
    surfaces = {}
    if obstacles is not None:
        surfaces['body'] = obstacles
    if settings.mode == 'terrain':
        surfaces['terrain'] = terrain_solid(terrain, rotation, centre, (low, high), centre[2])
    cells = np.maximum(4, np.ceil((high-low)/(length/settings.resolution))).astype(int)
    if np.prod(cells) > 1500000:
        raise ValueError('Background mesh exceeds 1.5 million cells. Reduce resolution.')
    keep = low + (high-low)*np.array([.02, .5, .8])
    manifest = dict(format=1, target='OpenCFD OpenFOAM v2312', settings=asdict(settings),
                    groups=[dict(uid=g.uid, name=g.name) for g in groups],
                    world_origin_m=centre.tolist(), world_to_wind=rotation.tolist(),
                    domain_m=[low.tolist(), high.tolist()], background_cells=cells.tolist(),
                    surfaces={k: len(v) for k,v in surfaces.items()},
                    status='exported; not simulated or validated',
                    notes=['Terrain edge heights are extended to the domain boundaries.' ] if terrain is not None else [])
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.wind-tunnel-', dir=destination.parent))
    try:
        for folder in ['0', 'constant/triSurface', 'system']:
            (stage/folder).mkdir(parents=True, exist_ok=True)
        for name, tris in surfaces.items():
            write_stl(stage/'constant/triSurface'/f'{name}.stl', tris)
        write_dictionaries(stage, settings, low, high, cells, keep, surfaces)
        (stage/'case.foam').touch()
        (stage/'ingetrazo-case.json').write_text(json.dumps(manifest, indent=2)+'\n')
        (stage/'README.txt').write_text(CASE_README)
        (stage/'Allrun').write_text(ALLRUN)
        (stage/'Allrun').chmod(0o755)
        stage.rename(destination)
    except Exception:
        shutil.rmtree(stage)
        raise
    return manifest


def write_dictionaries(root, s, low, high, cells, keep, surfaces):
    def write(path, body, cls='dictionary'):
        (root/path).write_text(header(Path(path).name, cls)+body+'\n')
    x0,y0,z0 = low; x1,y1,z1 = high
    vertices = [(x0,y0,z0),(x1,y0,z0),(x1,y1,z0),(x0,y1,z0),
                (x0,y0,z1),(x1,y0,z1),(x1,y1,z1),(x0,y1,z1)]
    boundary = 'inlet { type patch; faces ((0 4 7 3)); }\noutlet { type patch; faces ((1 2 6 5)); }\n'
    boundary += 'sides { type symmetryPlane; faces ((0 1 5 4) (3 7 6 2)); }\n'
    # Opposing parallel faces cannot share symmetryPlane (normals differ).
    boundary = boundary.replace('sides { type symmetryPlane; faces ((0 1 5 4) (3 7 6 2)); }',
                                'sideA { type symmetryPlane; faces ((0 1 5 4)); }\nsideB { type symmetryPlane; faces ((3 7 6 2)); }')
    boundary += 'top { type symmetryPlane; faces ((4 5 6 7)); }\n'
    boundary += 'bottom { type '+('wall' if s.mode == 'terrain' else 'symmetryPlane')+'; faces ((0 3 2 1)); }\n'
    write('system/blockMeshDict', 'scale 1;\nvertices (\n'+'\n'.join(map(vec, vertices))+'\n);\nblocks (hex (0 1 2 3 4 5 6 7) ('+' '.join(map(str,cells))+') simpleGrading (1 1 1));\nedges ();\nboundary (\n'+boundary+');\nmergePatchPairs ();')
    write('system/surfaceFeatureExtractDict', '\n'.join(f'{n}.stl {{ extractionMethod extractFromSurface; extractFromSurfaceCoeffs {{ includedAngle 150; }} writeObj no; }}' for n in surfaces))
    layers = "\n".join(f'{n} {{ nSurfaceLayers 3; }}' for n in surfaces)
    geometry = '\n'.join(f'{n}.stl {{ type triSurfaceMesh; name {n}; }}' for n in surfaces)
    features = '\n'.join(f'{{ file "{n}.eMesh"; level 2; }}' for n in surfaces)
    refinement = '\n'.join(f'{n} {{ level (2 3); patchInfo {{ type wall; }} }}' for n in surfaces)
    write('system/snappyHexMeshDict', f'''castellatedMesh true; snap true; addLayers true;
geometry {{ {geometry} }}
castellatedMeshControls
{{ maxLocalCells 2000000; maxGlobalCells 2000000; minRefinementCells 0;
   nCellsBetweenLevels 3; maxLoadUnbalance 0.1; features ({features});
   refinementSurfaces {{ {refinement} }} resolveFeatureAngle 30;
   refinementRegions {{ }} locationInMesh {vec(keep)}; allowFreeStandingZoneFaces true;
}}
snapControls {{ nSmoothPatch 3; tolerance 2; nSolveIter 30; nRelaxIter 5;
 nFeatureSnapIter 10; implicitFeatureSnap false; explicitFeatureSnap true; multiRegionFeatureSnap false; }}
addLayersControls
{{ relativeSizes true; layers {{ {layers} }}
 expansionRatio 1.2; finalLayerThickness 0.3; minThickness 0.1;
 nGrow 0; featureAngle 60; nRelaxIter 5; nSmoothSurfaceNormals 1;
 nSmoothNormals 3; nSmoothThickness 10; maxFaceThicknessRatio 0.5;
 maxThicknessToMedialRatio 0.3; minMedialAxisAngle 90;
 nBufferCellsNoExtrude 0; nLayerIter 50;
}}
meshQualityControls {{ #includeEtc "caseDicts/mesh/generation/meshQualityDict" }}
mergeTolerance 1e-6;
''')
    # OpenFOAM #include directives need their own line.
    file = root/'system/snappyHexMeshDict'
    file.write_text(file.read_text().replace('meshQualityControls { #includeEtc "caseDicts/mesh/generation/meshQualityDict" }', 'meshQualityControls\n{\n#includeEtc "caseDicts/mesh/generation/meshQualityDict"\n}'))
    model = 'kEpsilon' if s.mode == 'terrain' else 'kOmegaSST'
    write('constant/transportProperties', f'transportModel Newtonian;\nnu [0 2 -1 0 0 0 0] {s.viscosity:.10g};')
    write('constant/turbulenceProperties', f'simulationType RAS;\nRAS {{ RASModel {model}; turbulence on; printCoeffs on; }}')
    if s.mode == 'terrain':
        friction = .41*s.speed/math.log((s.reference_height+s.roughness)/s.roughness)
        k = friction**2/math.sqrt(.09)
        dissipation = friction**3/(.41*(s.reference_height+s.roughness))
        turb_field = 'epsilon'
    else:
        k = 1.5*(s.speed*s.intensity)**2
        dissipation = math.sqrt(k)/(.09**.25 * .07*s.reference_length)
        turb_field = 'omega'
    velocity = f'({s.speed:g} 0 0)'
    abl = f'flowDir (1 0 0); zDir (0 0 1); Uref {s.speed:g}; Zref {s.reference_height:g}; z0 uniform {s.roughness:g}; zGround uniform 0;'
    dims = {'U':'0 1 -1 0 0 0 0', 'p':'0 2 -2 0 0 0 0', 'k':'0 2 -2 0 0 0 0',
            'omega':'0 0 -1 0 0 0 0', 'epsilon':'0 2 -3 0 0 0 0', 'nut':'0 2 -1 0 0 0 0'}
    values = {'U':velocity, 'p':'0', 'k':f'{k:.10g}', turb_field:f'{dissipation:.10g}', 'nut':f'{.09*k*k/dissipation if turb_field == "epsilon" else k/dissipation:.10g}'}
    for field, value in values.items():
        if field == 'p':
            inlet = 'type zeroGradient;'; outlet = 'type fixedValue; value uniform 0;'
        elif field == 'nut':
            inlet = outlet = f'type calculated; value uniform {value};'
        else:
            inlet = f'type fixedValue; value uniform {value};'
            if s.mode == 'terrain':
                bc = {'U':'Velocity', 'k':'K', 'epsilon':'Epsilon'}[field]
                inlet = f'type atmBoundaryLayerInlet{bc}; {abl} value uniform {value};'
            outlet = f'type inletOutlet; inletValue uniform {value}; value uniform {value};'
        patches = [f'inlet {{ {inlet} }}', f'outlet {{ {outlet} }}']
        for patch in ['sideA', 'sideB', 'top'] + (['bottom'] if s.mode == 'aircraft' else []):
            patches.append(f'{patch} {{ type symmetryPlane; }}')
        for wall in list(surfaces) + (['bottom'] if s.mode == 'terrain' else []):
            if field == 'U':
                bc = 'type noSlip;'
            elif field == 'p':
                bc = 'type zeroGradient;'
            elif field == 'nut':
                bc = f'type atmNutkWallFunction; z0 uniform {s.roughness:g}; value uniform 0;' if wall in ('terrain', 'bottom') else 'type nutkWallFunction; value uniform 0;'
            else:
                bc = 'type '+{'k':'kqRWallFunction', 'omega':'omegaWallFunction', 'epsilon':'epsilonWallFunction'}[field]+f'; value uniform {value};'
            patches.append(f'{wall} {{ {bc} }}')
        write('0/'+field, f'dimensions [{dims[field]}];\ninternalField uniform {value};\nboundaryField\n{{\n'+ '\n'.join(patches)+'\n}', 'volVectorField' if field == 'U' else 'volScalarField')
    functions = '''residuals { type residuals; libs ("libutilityFunctionObjects.so"); fields (p U k '''+turb_field+'''); writeControl timeStep; writeInterval 1; }
wallYPlus { type yPlus; libs ("libfieldFunctionObjects.so"); writeControl writeTime; }
'''
    if s.mode == 'aircraft':
        functions += f'''forceCoeffs {{ type forceCoeffs; libs ("libforces.so"); patches (body);
 rho rhoInf; rhoInf {s.density:g}; CofR (0 0 0); liftDir (0 0 1); dragDir (1 0 0);
 pitchAxis (0 1 0); magUInf {s.speed:g}; lRef {s.reference_length:g}; Aref {s.reference_area:g};
 writeControl timeStep; writeInterval 1; }}\n'''
    write('system/controlDict', f'''application simpleFoam; startFrom startTime; startTime 0;
stopAt endTime; endTime {s.iterations}; deltaT 1;
writeControl timeStep; writeInterval {min(100,s.iterations)};
purgeWrite 0; writeFormat ascii; writePrecision 8; writeCompression off;
timeFormat general; timePrecision 8; runTimeModifiable true;
functions {{ {functions} }}
''')
    write('system/fvSchemes', f'''ddtSchemes {{ default steadyState; }}
gradSchemes {{ default cellLimited Gauss linear 1; }}
divSchemes {{ default none; div(phi,U) bounded Gauss linearUpwind grad(U);
 div(phi,k) bounded Gauss upwind; div(phi,{turb_field}) bounded Gauss upwind;
 div((nuEff*dev2(T(grad(U))))) Gauss linear; }}
laplacianSchemes {{ default Gauss linear limited 0.5; }}
interpolationSchemes {{ default linear; }}
snGradSchemes {{ default limited 0.5; }}
wallDist {{ method meshWave; }}
''')
    write('system/fvSolution', '''solvers {
p { solver GAMG; tolerance 1e-7; relTol 0.1; smoother GaussSeidel; }
"(U|k|omega|epsilon)" { solver smoothSolver; smoother symGaussSeidel; tolerance 1e-8; relTol 0.1; }
}
SIMPLE { nNonOrthogonalCorrectors 2; consistent yes;
 residualControl { p 1e-4; U 1e-5; "(k|omega|epsilon)" 1e-5; } }
relaxationFactors { fields { p 0.3; } equations { U 0.7; k 0.7; omega 0.7; epsilon 0.7; } }
''')


ALLRUN = '''#!/usr/bin/env bash
set -eo pipefail
cd -- "$(dirname -- "$0")"
if [ "${WM_PROJECT_VERSION#v}" != 2312 ]; then
    echo "Requires OpenCFD OpenFOAM v2312. Source its etc/bashrc first."; exit 2
fi
for utility in blockMesh surfaceFeatureExtract snappyHexMesh checkMesh simpleFoam; do
    command -v "$utility" >/dev/null || { echo "Missing $utility: source OpenCFD OpenFOAM v2312 etc/bashrc first."; exit 1; }
done
if [ -d constant/polyMesh ]; then
    echo "This case already has a mesh. Export a new case to protect existing results."; exit 1
fi
blockMesh 2>&1 | tee log.blockMesh
surfaceFeatureExtract 2>&1 | tee log.surfaceFeatureExtract
snappyHexMesh -overwrite 2>&1 | tee log.snappyHexMesh
checkMesh -allTopology -allGeometry 2>&1 | tee log.checkMesh
grep -q 'Mesh OK.' log.checkMesh || { echo "Mesh quality failed; solver not started."; exit 1; }
simpleFoam 2>&1 | tee log.simpleFoam
'''
CASE_README = '''IngeTrazo Virtual Wind Tunnel — exploratory OpenCFD OpenFOAM v2312 case

All geometry is in metres, translated near the origin and rotated into a wind
frame with airflow towards +X. ingetrazo-case.json records the inverse mapping,
settings, source groups and domain. Pressure p is kinematic pressure (m²/s²);
multiply by air density for Pa. Coefficients use the entered reference area
and length. A steady iteration is not a physical time step.

Run in a configured OpenCFD v2312 environment: bash Allrun
Or use IngeTrazo's Docker backend (opencfd/openfoam-default:2312).
Open case.foam in ParaView, select the latest time, click Apply, colour by U
Magnitude or p, add Slice or Stream Tracer. Force coefficients and residuals
are in postProcessing. Use wallYPlus to inspect wall-function suitability.

These generated cases have not established aerodynamic prediction accuracy.
Check residuals AND forces, boundary-layer resolution, domain size and mesh
independence. Low-Reynolds-number transition, stall, rotating propellers,
thermal terrain effects and transient moving geometry are outside this preset.
Three requested wall layers are a starting point; meshing may remove layers.
The exporter checks surface edge closure and orientation, not all intersections.
Terrain boundary heights are clamped to the imported DEM edge and extended;
inspect inlet terrain and use a sufficiently large source DEM.

References:
https://doc.openfoam.com/2312/tools/pre-processing/mesh/generation/snappyhexmesh/
https://doc.openfoam.com/2312/tools/processing/boundary-conditions/rtm/derived/atmospheric/atmBoundaryLayer/
https://hub.docker.com/r/opencfd/openfoam-default/tags
'''
