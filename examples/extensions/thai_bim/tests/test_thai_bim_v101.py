import importlib,sys,types,unittest,copy
from pathlib import Path
p=types.ModuleType('tb101pure');p.__path__=[str(Path(__file__).resolve().parents[1])];sys.modules[p.__name__]=p
I=importlib.import_module('tb101pure.identity_data')
class CopyIdentityTests(unittest.TestCase):
    def test_declared_original_preserved_even_when_copy_precedes_it(self):
        r=dict(id='business',native_uid='original',kind='Column',assembly='grid-columns',member_type=dict(id='C1'))
        rows=[('copy',copy.deepcopy(r)),('original',r)];result=dict(I.repaired(rows))
        self.assertEqual(result['original']['id'],'business');self.assertNotEqual(result['copy']['id'],'business')
        self.assertEqual(result['copy']['assembly'],'copy-copy');self.assertEqual(result['copy']['member_type'],r['member_type'])
        self.assertEqual(rows[0][1],r)
    def test_legacy_owner_prefers_referenced_host(self):
        rows=[('copy',dict(id='host',kind='Column')),('original',dict(id='host',kind='Column')),('bar',dict(id='bar',kind='Rebar',host_uid='original'))]
        result=dict(I.repaired(rows));self.assertEqual(result['original']['id'],'host');self.assertEqual(result['bar']['host_uid'],'original')
    def test_copied_bars_do_not_join_original_host_or_assembly(self):
        r=dict(id='bar',native_uid='a',kind='Rebar',host_uid='host',assembly='rebar-host')
        result=dict(I.repaired([('a',r),('b',copy.deepcopy(r))]))
        self.assertEqual(result['a']['host_uid'],'host');self.assertTrue(result['b']['copy_review_required'])
        self.assertEqual(result['b']['copied_from_host_uid'],'host');self.assertNotEqual(result['b']['host_uid'],'host')
    def test_missing_ids_and_idempotency(self):
        rows=[('a',dict(kind='Footing')),('b',dict(kind='Column'))];result=I.repaired(rows)
        self.assertEqual(len({r['id'] for uid,r in result}),2);self.assertEqual(I.repaired(result),result)
    def test_native_uid_collision_is_not_guessed(self):
        with self.assertRaises(ValueError):I.repaired([('a',dict(id='x')),('a',dict(id='y'))])
    def test_copy_survives_deleted_original_without_false_host_association(self):
        r=dict(id='bar',native_uid='deleted',kind='Rebar',host_uid='host')
        result=dict(I.repaired([('copy',r)]))['copy']
        self.assertNotEqual(result['id'],'bar');self.assertTrue(result['copy_review_required'])
