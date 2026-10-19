import importlib,sys,types,unittest
from pathlib import Path
p=types.ModuleType('tb071pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
A=importlib.import_module('tb071pure.audit')
class AuditTests(unittest.TestCase):
    def test_legacy_is_not_detailed_bbs(self):
        rows=[dict(uid='a',origin='family10',record=dict(id='F10-1',discipline='Structure',item='Tie',**{'class':'IfcReinforcingBar'}),layer='Rebar'),dict(uid='b',origin=None,record={},layer=None)]
        r=A.summarize(rows,{'Rebar':False,'Layer 0':True})
        self.assertEqual(r['tagged'],1);self.assertEqual(r['untagged'],1);self.assertEqual(r['legacy_rebar_count'],1)
    def test_identity_and_missing_layer(self):
        e=dict(uid='a',origin='thai_bim',record=dict(id='x',kind='Column'),layer='Missing')
        r=A.summarize([e,e],{})
        self.assertTrue(any('Duplicate native UID' in s for s in r['issues']))
        self.assertTrue(any('Duplicate metadata ID' in s for s in r['issues']))
        self.assertTrue(any('Missing layer' in s for s in r['issues']))
if __name__=='__main__':unittest.main()
