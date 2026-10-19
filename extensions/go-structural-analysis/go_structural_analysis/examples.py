"""Editable benchmark catalogue. No solver or Qt imports."""
if __package__:
    from .model import benchmark, validate
else:
    from model import benchmark, validate

CATALOG = [
    ('simple_udl', 'Simply Supported Beam — UDL', 'R=30/30 kN; |M|max=45 kN.m; |D|max=10.546875 mm.'),
    ('simple_point', 'Simply Supported Beam — Point Load', 'P=20 kN at 3 m; R=10/10 kN; |M|max=30 kN.m.'),
    ('cantilever_point', 'Cantilever — Point Load', 'L=6 m, tip P=10 kN; R=10 kN; support moment=60 kN.m; Dtip=-45 mm.'),
    ('cantilever_udl', 'Cantilever — UDL', 'w=10 kN/m; R=60 kN; support moment=180 kN.m; Dtip=-101.25 mm.'),
    ('continuous_2', 'Continuous Beam — 2 spans', '6 m/span; reactions 22.5, 75, 22.5 kN; interior |M|=45 kN.m.'),
    ('continuous_3', 'Continuous Beam — 3 spans', '6 m/span; reactions 24, 66, 66, 24 kN; interior |M|=36 kN.m.'),
    ('portal_vertical', 'Portal Frame — Vertical load', '6 x 4 m fixed-base portal; top beam UDL 10 kN/m. Compare independent frame-stiffness reference.'),
    ('portal_horizontal', 'Portal Frame — Horizontal load', '6 x 4 m fixed-base portal; FX=10 kN at upper-left joint. Check sway and equilibrium.'),
    ('inclined', 'Inclined Frame — Transformation', 'Fixed-to-free member (0,0) to (-6,4); FX=7, FZ=-10 kN at tip. Compare global/local displacement.'),
    ('truss', '2D Truss — Joint load', 'Triangle 6 m wide, 3 m high; top P=10 kN. N bottom=-5; diagonals=+7.071068 kN (+compression).'),
    ('release_j', 'Member Release — j end', 'Fixed nodes, release j; R=37.5/22.5 kN; j-end moment=0.'),
    ('release_both', 'Member Releases — both ends', 'Fixed nodes, release i/j; R=30/30 kN; both end moments=0.'),
    ('unstable_loaded', 'Stability — released mechanism (loaded)', 'EXPECTED FAILURE: released cantilever is unstable. Solver must reject; no valid diagrams.'),
    ('unstable_unloaded', 'Stability — released mechanism (unloaded)', 'EXPECTED FAILURE: zero load does not make a mechanism stable. Solver must reject.'),
    ('cases_off', 'Multiple Load Cases — self-weight OFF', 'LC1: UDL, total RZ=60 kN. LC2: joint load, total RZ=5 kN. Switch Results > Load Case.'),
    ('cases_on', 'Multiple Load Cases — self-weight ON', 'Total member weight=4.6188 kN per case; total RZ LC1=64.6188, LC2=9.6188 kN.'),
    ('truss_weight', '2D Truss — self-weight ON', 'Member weight lumped equally at joints; axial-only response. Compare with self-weight OFF.'),
    ('off_grid', 'Exact Extrema — off-grid point load', '20 kN at x=1.37 m; moment extremum at load. Inspector left/right shows shear jump=-20 kN.'),
    ('triangular', 'Exact Extrema — triangular UDL', 'w=0 to -10 kN/m; R=10/20 kN; moment extremum x=6/sqrt(3) m.'),
    ('axial', 'Axial — distributed load', 'Cantilever q=+3 kN/m in X; RX=-18 kN; tip UX=0.027 mm.'),
    ('moment_jump', 'Moment — concentrated member moment', 'MY=10 kN.m at x=2 m; reactions +/-10/6 kN; section moment jump=10 kN.m.'),
]


def example(key):
    if key not in {row[0] for row in CATALOG}:
        raise ValueError('Unknown benchmark: ' + str(key))
    d = benchmark()
    if key == 'simple_point' or key == 'off_grid':
        d['distributed_loads'] = []
        d['point_loads'] = [dict(member='B1', direction='FZ', value=-20., x=1.37 if key == 'off_grid' else 3., case='LC1')]
    elif key.startswith('cantilever') or key == 'inclined' or key == 'axial':
        d['nodes'][0]['support'] = 'Fixed'
        d['nodes'][1]['support'] = 'Free'
        if key == 'cantilever_point':
            d['distributed_loads'] = []
            d['point_loads'] = [dict(node='N2', direction='FZ', value=-10., case='LC1')]
        elif key == 'inclined':
            d['nodes'][1].update(x=-6., z=4.)
            d['members'][0]['type'] = 'Frame'
            d['distributed_loads'] = []
            d['point_loads'] = [dict(node='N2', direction=axis, value=value, case='LC1') for axis,value in [('FX',7.),('FZ',-10.)]]
        elif key == 'axial':
            d['distributed_loads'][0].update(direction='FX', w1=3., w2=3.)
    elif key.startswith('continuous'):
        spans = int(key[-1])
        d['nodes'] = [dict(id=f'N{i}', x=i*6., z=0., support='Pin' if i==0 else 'Roller') for i in range(spans+1)]
        d['members'] = [dict(d['members'][0], id=f'B{i}', i=f'N{i}', j=f'N{i+1}') for i in range(spans)]
        d['distributed_loads'] = [dict(member=f'B{i}', direction='FZ', w1=-10., w2=-10., case='LC1') for i in range(spans)]
    elif key.startswith('portal'):
        d['nodes'] = [dict(id=n, x=x, z=z, support=s) for n,x,z,s in [('A',0.,0.,'Fixed'),('B',0.,4.,'Free'),('C',6.,4.,'Free'),('D',6.,0.,'Fixed')]]
        d['members'] = [dict(d['members'][0], id=mid, i=a, j=b, type='Frame') for mid,a,b in [('AB','A','B'),('BC','B','C'),('CD','C','D')]]
        d['distributed_loads'] = []
        if key == 'portal_vertical': d['distributed_loads'] = [dict(member='BC', direction='FZ', w1=-10., w2=-10., case='LC1')]
        else: d['point_loads'] = [dict(node='B', direction='FX', value=10., case='LC1')]
    elif key in ('truss','truss_weight'):
        d['nodes'].append(dict(id='N3', x=3., z=3., support='Free'))
        d['members'][0]['type'] = 'Truss'
        d['members'] += [dict(d['members'][0], id=mid, i=a, j=b) for mid,a,b in [('T2','N1','N3'),('T3','N3','N2')]]
        d['distributed_loads'] = []
        d['point_loads'] = [dict(node='N3', direction='FZ', value=-10., case='LC1')]
        d['self_weight'] = key == 'truss_weight'
    elif key.startswith('release') or key.startswith('unstable'):
        d['nodes'][0]['support'] = 'Fixed'
        d['nodes'][1]['support'] = 'Free' if key.startswith('unstable') else 'Fixed'
        d['members'][0]['release_j'] = True
        d['members'][0]['release_i'] = key != 'release_j'
        if key == 'unstable_unloaded': d['distributed_loads'] = []
    elif key.startswith('cases'):
        d['cases'] = ['LC1','LC2']
        d['point_loads'] = [dict(node='N1', direction='FZ', value=-5., case='LC2')]
        d['self_weight'] = key == 'cases_on'
    elif key == 'triangular': d['distributed_loads'][0]['w1'] = 0.
    elif key == 'moment_jump':
        d['distributed_loads'] = []
        d['point_loads'] = [dict(member='B1', direction='MY', value=10., x=2., case='LC1')]
    return validate(d)
