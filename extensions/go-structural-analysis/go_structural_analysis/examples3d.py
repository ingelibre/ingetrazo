"""Editable 3D benchmarks; example combinations are user factors, not a design code."""
import copy
from .model3d import cantilever3d

CATALOG3D=[
 ('3d_cantilever','3D Cantilever — two-axis loading','Closed form PL³/3EI on both lateral axes.'),
 ('3d_torsion','3D Cantilever — pure torsion','Twist TL/GJ; internal torque sign follows local cut convention.'),
 ('3d_axial','3D Axial member','Elongation PL/EA, compression-positive N.'),
 ('3d_portal','3D Portal frame','Independent 12-DOF direct-stiffness reference.'),
 ('3d_truss','Space Truss — tripod','Joint equilibrium and independent axial-bar stiffness.'),
 ('3d_multibay','Multi-bay 3D frame','Two bays in X and Y; independent direct-stiffness reference.'),
 ('3d_rotation','Local section rotation — 37 degrees','Unequal Iy/Iz; transformed closed-form bending flexibility.'),
 ('3d_release','Member end release','Rotational release at simply supported end; moment = 0.'),
 ('3d_selfweight','Self-weight — DL only','Weight rho A L; compare automatic ON/OFF.'),
 ('3d_combo','Load combinations — linear','ULS = 1.4DL + 1.7LL; factors are illustrative only.'),
 ('3d_equilibrium','Inclined member — global equilibrium','XYZ forces/moments and partial varying local loading.'),
 ('3d_unstable','Unstable 3D structure — expected rejection','Pin-supported cantilever is a mechanism; must fail.')]

def example3d(key):
    if key=='3d_house_phetnaray':
        from .house_example import house_model
        return house_model()
    d=cantilever3d(); base=copy.deepcopy(d['members'][0])
    if key=='3d_cantilever': pass
    elif key=='3d_torsion': d['point_loads']=[dict(node='N2',direction='MX',value=8,case='DL')]
    elif key=='3d_axial': d['point_loads']=[dict(node='N2',direction='FX',value=25,case='DL')]
    elif key in ('3d_portal','3d_multibay'):
        count=1 if key=='3d_portal' else 2; coords={}
        for ix in range(count+1):
            for iy in range(count+1):
                for level in (0,1): coords[(ix,iy,level)]='N'+str(len(coords)+1)
        d['nodes']=[dict(id=name,x=ix*4,y=iy*3,z=level*3,support='Fixed' if level==0 else 'Free') for (ix,iy,level),name in coords.items()]
        d['members']=[]
        def add(a,b,kind='Frame'):
            d['members'].append(dict(base,id='M'+str(len(d['members'])+1),i=coords[a],j=coords[b],type=kind))
        for ix in range(count+1):
            for iy in range(count+1):
                add((ix,iy,0),(ix,iy,1),'Column')
                if ix<count: add((ix,iy,1),(ix+1,iy,1))
                if iy<count: add((ix,iy,1),(ix,iy+1,1))
        d['point_loads']=[]
        for (ix,iy,level),node in coords.items():
            if level:
                d['point_loads']+= [dict(node=node,direction='FZ',value=-12,case='DL'),dict(node=node,direction='FX',value=5,case='WX'),dict(node=node,direction='FY',value=3,case='WY')]
    elif key=='3d_truss':
        d['nodes']=[dict(id='N1',x=0,y=0,z=0,support='Pin'),dict(id='N2',x=4,y=0,z=0,support='Pin'),dict(id='N3',x=0,y=3,z=0,support='Pin'),dict(id='N4',x=1,y=1,z=3,support='Free')]
        d['members']=[dict(base,id='T'+str(i),i='N'+str(i),j='N4',type='Truss') for i in (1,2,3)]
        d['point_loads']=[dict(node='N4',direction='FZ',value=-30,case='DL'),dict(node='N4',direction='FX',value=7,case='DL'),dict(node='N4',direction='FY',value=-3,case='DL')]
    elif key=='3d_rotation': d['members'][0]['rotation']=37; d['sections'][0].update(Iy=2e-5,Iz=8e-5)
    elif key=='3d_release':
        d['nodes'][0]['support']='Fixed'; d['nodes'][1].update(support='Custom',restraints=['UY','UZ','RX','RY','RZ'])
        d['members'][0]['release_j']=['RZ']; d['point_loads']=[]
        d['distributed_loads']=[dict(member='B1',direction='FZ',w1=-10,w2=-10,case='DL')]
    elif key=='3d_selfweight': d.update(self_weight=True,point_loads=[])
    elif key=='3d_combo': d['combinations']={'ULS':{'DL':1.4,'LL':1.7},'Reverse':{'DL':-1,'LL':-1}}
    elif key=='3d_equilibrium':
        d['nodes'][1].update(x=3,y=2,z=4); d['members'][0]['rotation']=23
        d['point_loads']+=[dict(member='B1',direction='Mx',value=8,x=1.75,case='DL')]
        d['distributed_loads']=[dict(member='B1',direction='Fy',w1=-3,w2=7,x1=.37,x2=4.5,case='DL')]
    elif key=='3d_unstable': d['nodes'][0]['support']='Pin'; d['point_loads']=[]
    else: raise KeyError(key)
    return d
