import importlib,sys,types,unittest,math
from pathlib import Path
package=types.ModuleType('tb04pure');package.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules['tb04pure']=package
E=importlib.import_module('tb04pure.engine');S=importlib.import_module('tb04pure.structures')

def volume(faces):
    return sum(E.dot(f[0],E.cross(f[i],f[i+1]))/6 for f in faces for i in range(1,len(f)-1))

class BuilderTests(unittest.TestCase):
    def test_roofs(self):
        for kind,number in [('Gable',2),('Shed',1),('Hip',4)]:
            for w,d in [(6,4),(4,6),(6,6)]:
                planes,specs=S.roof_assembly(kind,width=w,depth=d)
                self.assertEqual(len(planes),number)
                self.assertTrue(all(volume(s['faces'])>0 for s in specs))
                for p in planes:E.plane_geometry(p['vertices'])
                covers=[s for s in specs if s['kind']=='Roof cover']
                expected=(w+.8)*(d+.8)/math.cos(math.radians(30))
                self.assertAlmostEqual(sum(s['quantity'] for s in covers),expected,places=8)
                self.assertAlmostEqual(sum(volume(s['faces']) for s in covers),expected*.06,places=8)
    def test_roof_validation(self):
        for kwargs in [dict(width=0),dict(pitch=float('nan')),dict(overhang=-.1),dict(rafter_spacing=0)]:
            with self.assertRaises(ValueError):S.roof_assembly('Hip',**kwargs)
    def test_stair_volume_and_last_riser(self):
        for n in [2,18,27,60]:
            s=S.stair_spec(risers=n)
            self.assertAlmostEqual(volume(s['faces']),s['quantity'],places=8)
            self.assertAlmostEqual(max(v[2] for f in s['faces'] for v in f),3)
        with self.assertRaises(ValueError):S.stair_spec(risers=18.5)
    def test_bar_solid_volume_and_tie(self):
        for closed,points in [(False,[(0,0,0),(0,0,3)]),(False,[(0,0,0),(1,2,3)]),(True,[(0,0,0),(1,0,0),(1,2,0),(0,2,0)])]:
            s=S.bar_spec('b',points,.012,closed)
            expected=12/2*(.012/2)**2*math.sin(2*math.pi/12)*s['quantity']
            self.assertAlmostEqual(volume(s['faces']),expected,places=9)
    def test_all_hosts(self):
        for kind,w,d,h in [('Footing',1.2,1.2,.4),('Slab',4,3,.15),('Beam',3,.25,.4),('Column',.25,.25,3)]:
            p=E.box_spec(kind,0,0,0,w,d,h)['params'];specs=S.reinforcement(kind,p)
            self.assertGreater(len(specs),4)
            self.assertTrue(all(s['quantity']>0 and volume(s['faces'])>0 for s in specs))
            for s in specs:
                for face in s['faces']:
                    for x,y,z in face:
                        self.assertGreaterEqual(min(x,y,z),.04-1e-9)
                        self.assertLessEqual(x,w-.04+1e-9);self.assertLessEqual(y,d-.04+1e-9);self.assertLessEqual(z,h-.04+1e-9)
        p=S.stair_spec()['stair_params'];specs=S.reinforcement('Stair',p)
        self.assertTrue(all(volume(s['faces'])>0 for s in specs))
    def test_spacing_and_two_layers(self):
        p=E.box_spec('Slab',0,0,0,4,3,.2)['params']
        one=S.reinforcement('Slab',p,layers=1);two=S.reinforcement('Slab',p,layers=2)
        self.assertEqual(len(two),len(one)*2)
        ys=sorted(s['bar_path'][0][1] for s in one if abs(s['bar_path'][1][0]-s['bar_path'][0][0])>1)
        self.assertLessEqual(max(b-a for a,b in zip(ys,ys[1:])),.15+1e-9)
    def test_rebar_invalid(self):
        p=E.box_spec('Column',0,0,0,.1,.1,3)['params']
        with self.assertRaises(ValueError):S.reinforcement('Column',p)
        p=E.box_spec('Slab',0,0,0,4,3,.1)['params']
        with self.assertRaises(ValueError):S.reinforcement('Slab',p,layers=2)
        with self.assertRaises(ValueError):S.reinforcement('Slab',p,count_x=2.5)
        p=E.box_spec('Column',0,0,0,.25,.25,3)['params']
        with self.assertRaises(ValueError):S.reinforcement('Column',p,count_x=30)

if __name__=='__main__':unittest.main()
