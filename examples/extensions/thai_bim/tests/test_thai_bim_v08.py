import importlib,sys,types,unittest,math
from pathlib import Path
p=types.ModuleType('tb08pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
D=importlib.import_module('tb08pure.detailing');E=importlib.import_module('tb08pure.engine');S=importlib.import_module('tb08pure.structures')

class V08Tests(unittest.TestCase):
    def test_slab_hooks_exact_length_and_layers(self):
        host=E.box_spec('Slab',0,0,0,2,3,.3)['params']
        straight=D.reinforcement('Slab',host,layers=2,representation='Centreline')
        hooked=D.reinforcement('Slab',host,layers=2,hook_length=.025,representation='Centreline')
        self.assertEqual(len(straight),len(hooked))
        r=.024+.012/2
        for a,b in zip(straight,hooked):
            self.assertAlmostEqual(b['quantity']-a['quantity'],2*.025-2*r+math.pi*r)
            self.assertEqual(b['bbs']['bend_degrees'],[90,90])
            self.assertEqual(b['slot'],a['slot'])
        self.assertTrue(any(b['bar_path'][0][2]>b['bar_path'][-2][2] for b in hooked))
        self.assertTrue(any(b['bar_path'][0][2]<b['bar_path'][-2][2] for b in hooked))
    def test_stair_vertical_hook_angles_and_tail(self):
        host=S.stair_spec(waist=.24)['stair_params']
        bars=D.reinforcement('Stair',host,hook_length=.025,representation='Centreline')
        hook=next(b for b in bars if b['bbs']['shape']=='Stair-U')
        slope=host['height']/host['risers']/host['going'];theta=math.degrees(math.atan(slope))
        self.assertAlmostEqual(hook['bbs']['bend_degrees'][0],90+theta,places=5)
        self.assertAlmostEqual(hook['bbs']['bend_degrees'][1],90-theta,places=5)
        self.assertAlmostEqual(hook['bbs']['straight_mm'][0],25)
        self.assertAlmostEqual(hook['bbs']['straight_mm'][-1],25)
        self.assertTrue(any(b['bbs']['shape']=='Straight' for b in bars))
    def test_stair_extensions_only_main_and_mass(self):
        host=S.stair_spec()['stair_params']
        a=D.reinforcement('Stair',host,representation='Centreline')
        b=D.reinforcement('Stair',host,extension_start=.3,extension_end=.4,representation='Centreline')
        for old,new in zip(a,b):
            delta=.7 if abs(old['bar_path'][0][0]-old['bar_path'][-1][0])>.1 else 0
            self.assertAlmostEqual(new['quantity']-old['quantity'],delta)
            self.assertAlmostEqual(new['bbs']['mass_kg'],new['quantity']*math.pi*.012**2/4*7850)
    def test_display_modes_preserve_marks_and_cut_length(self):
        for kind,host,opts in [('Slab',E.box_spec('Slab',0,0,0,2,3,.3)['params'],dict(layers=2,hook_length=.025)),
                               ('Stair',S.stair_spec(waist=.24)['stair_params'],dict(hook_length=.025))]:
            variants=[D.reinforcement(kind,host,representation=m,**opts) for m in ('Full','Lightweight','Centreline')]
            for a,b,c in zip(*variants):self.assertEqual(a['bbs'],b['bbs']);self.assertEqual(a['bbs'],c['bbs'])
            self.assertTrue(all(not b['faces'] for b in variants[-1]))
    def test_invalid_details_rejected(self):
        slab=E.box_spec('Slab',0,0,0,2,3,.15)['params'];stair=S.stair_spec()['stair_params']
        for kind,host,opts in [('Slab',slab,dict(hook_length=.2)),('Slab',slab,dict(lap_length=.3)),
                               ('Stair',stair,dict(hook_length=.3)),('Stair',stair,dict(lap_length=.3)),
                               ('Stair',stair,dict(hook_length=.01,extension_start=.3))]:
            with self.assertRaises(ValueError):D.reinforcement(kind,host,representation='Centreline',**opts)
    def test_steep_stair_main_bar_extensions(self):
        host=S.stair_spec(height=3,risers=4,going=.2)['stair_params']
        a=D.reinforcement('Stair',host,representation='Centreline')
        b=D.reinforcement('Stair',host,extension_start=.2,representation='Centreline')
        self.assertTrue(any(abs(n['quantity']-o['quantity']-.2)<1e-8 for o,n in zip(a,b)))

if __name__=='__main__':unittest.main()
