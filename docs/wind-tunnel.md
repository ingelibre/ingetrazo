# Virtual Wind Tunnel

**Extensions → Virtual Wind Tunnel** prepares an external-flow calculation for
**OpenCFD OpenFOAM v2312**. It exports a fresh case, runs meshing and steady RANS
steps, and opens the case in ParaView. CFD is an external dependency; installing
IngeTrazo does not install OpenFOAM, Docker or ParaView.

## Preparing the model

For **aircraft**, create closed solid groups and select the ones to analyse.
The checklist is explicit: unchecked groups are not exported. Meshes are exported
in world metres, including nested group and instance transforms. Open surfaces,
nonmanifold edges, degenerate triangles and inconsistent face directions are
rejected. The edge checks do not detect every self-intersection or intersection
between solids; repair or union overlapping solids before exporting. Loose faces,
billboards, textures and drawing guides are not part of the aerodynamic model.

For **terrain**, load the 3D elevation terrain using the existing georeferencing
workflow. A flat map image has no elevation data. Check any closed building or
obstacle groups to include. The terrain is resampled into the wind frame and
closed beneath the computational domain. Outside the source DEM, heights are
clamped to its edge and extended to the domain boundary. This is an artificial
boundary treatment: use a large DEM, inspect the inlet terrain, and compare
larger-domain runs. The domain excludes the solid ground below the terrain.

## Wind and mesh

- Speed is m/s. **Flow TOWARDS** is a mathematical direction, not the
  meteorological wind-from bearing: 0° is model +X, 90° is model +Y.
- Aircraft angle of attack rotates the model about the wind-frame Y axis.
  For an aerofoil with leading edge at X=0 and trailing edge at positive X,
  positive angle puts the trailing edge below the leading edge.
- Density is kg/m³; viscosity is **kinematic** viscosity in m²/s.
- Enter actual wing reference area and chord to get meaningful force
  coefficients. Defaults of 1 m² / 1 m are placeholders.
- Terrain speed is specified at the reference height above the lowest DEM
  elevation. Terrain uses a neutral log-law inlet and rough ground wall
  functions; roughness length is in metres. Aircraft uses a uniform inlet.
- Aircraft uses k–omega SST; terrain uses k–epsilon. The aircraft preset is
  fully turbulent and does not model transition, making small low-Re wings
  especially dependent on independent validation.
- Background cells per model extent sets the coarse grid; surfaces then
  refine 2–3 levels. Three prism layers are requested. SnappyHexMesh may
  remove layers to preserve quality: inspect the mesh and y-plus results.
- Iterations are convergence iterations of a **steady** calculation, not
  physical time. A steady solution cannot resolve changing turbulence,
  wing motion, propeller rotation or transient stall.

Aircraft bounds extend 5 model extents upstream, 10 downstream and 5 sideways
and vertically. Terrain bounds extend 1 extent upstream, 2 downstream, 0.5
sideways and at least 1 above the highest point. This first version exports
these automatic bounds in the manifest for inspection; it does not have an
interactive domain editor.

## Export and run

1. Choose **Export a new wind-tunnel case** and a parent directory. A unique
   timestamped case folder is created. Existing cases are never overwritten.
2. On **Calculation and results**, choose a backend:
   - **Docker**: install and start Docker Desktop on macOS. The extension uses
     `opencfd/openfoam-default:2312`, which has arm64 and amd64 images. First
     Run downloads the image; subsequent runs reuse it. Each stage has a
     named container, limited to 4 CPUs and 6 GB RAM. Allow enough memory in
     Docker Desktop. Only the case directory is mounted in the container.
   - **Native**: use an OpenCFD v2312 environment, or enter its `etc/bashrc`.
     The extension checks the version before launching each utility. Other
     OpenFOAM distributions/versions are not automatically assumed compatible.
3. Click **Mesh and run**. The sequence is blockMesh → surfaceFeatureExtract →
   snappyHexMesh → checkMesh → simpleFoam. The UI remains responsive and shows
   utility output. A failed utility or missing `Mesh OK.` prevents solving.
4. **Stop** terminates the active native utility or stops its Docker container.
   Partial files and logs remain available. Export a new case for another run.
5. **Open results in ParaView** opens `case.foam` using the selected ParaView
   executable. On macOS this is usually inside ParaView.app/Contents/MacOS.
   Choose the latest time, Apply, colour by U Magnitude or p, then add Slice or
   Stream Tracer. Pressure p is kinematic pressure (m²/s²); multiply by density
   for Pa. The geometry is shown in wind coordinates, not its original position.

Cases are portable: copy the case folder to a Linux computer with OpenCFD
v2312, source its environment and run `bash Allrun`. Automatic SSH upload and
remote job management are not included in this version.

`ingetrazo-case.json` records input settings, included groups, coordinate
mapping and bounds. `ingetrazo-run.json` records runner status. Stage logs are
`log.blockMesh`, etc. `postProcessing` contains residuals, y-plus and, for
an aircraft, force coefficients. IngeTrazo stores the settings and case path
in the model's extension data; save the `.igz` to retain those references.
It does not embed the potentially large CFD result files in the model.

## Validation status and procedure

The exporter and runner have automated tests for units, transforms, closed
surfaces, atmospheric dictionaries, fresh-case protection, failed mesh gating,
cancellation, and reporting iteration limits without claiming convergence.
**These tests are not a CFD validation.** No successful OpenFOAM calculation or
comparison against experimental aerofoil data has yet been recorded for this
integration. An exported case is clearly identified as not simulated.

Before using predictions:

1. Establish a working OpenCFD v2312 installation and run its supplied
   `incompressible/simpleFoam/airFoil2D` and `turbineSiting` tutorial cases.
2. Compare aircraft coefficients against an appropriate published benchmark,
   matching Reynolds number, geometry, boundary conditions and dimensionality.
   A finite extruded wing is not equivalent to a two-dimensional aerofoil test.
3. Check y-plus, prism-layer coverage, residuals and force histories. Reaching
   the iteration limit does not prove convergence; falling residuals alone do
   not prove force accuracy.
4. Repeat with finer meshes and larger domains. Compare lift/drag and terrain
   wind speeds at fixed points until changes are acceptably small.
5. Test terrain with an empty flat-domain case: inlet profiles should persist
   downstream before adding hills and obstacles.

## Sources

- [OpenFOAM snappyHexMesh](https://doc.openfoam.com/2312/tools/pre-processing/mesh/generation/snappyhexmesh/)
- [Atmospheric inlet formulation](https://doc.openfoam.com/2312/tools/processing/boundary-conditions/rtm/derived/atmospheric/atmBoundaryLayer/)
- [Atmospheric wall function](https://doc.openfoam.com/2606/tools/processing/boundary-conditions/rtm/derived/atmospheric/atmNutkWallFunction/)
- [Official OpenCFD container tags](https://hub.docker.com/r/opencfd/openfoam-default/tags)
- [OpenFOAM on Mac](https://www.openfoam.com/download/openfoam-installation-on-mac-using-docker)
- [ParaView](https://www.paraview.org/download/)
