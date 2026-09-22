import importlib.util,json,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('profile_revision_test',ROOT/'错题知识网络/scripts/math_learning_profiles.py');profiles=importlib.util.module_from_spec(spec);spec.loader.exec_module(profiles)
class ProfileRevisionTests(unittest.TestCase):
 def test_exact_predecessor_is_required_and_original_bytes_are_preserved(self):
  with tempfile.TemporaryDirectory() as d:
   root=Path(d);old={'concept_key':'MATH-CONCEPT-fixture','event_id':'real-event','overview':'original'};old['content_sha256']=profiles.digest(old)
   path=root/profiles.SEMANTIC/'MATH-CONCEPT-fixture.json';path.parent.mkdir(parents=True);raw=(json.dumps(old,ensure_ascii=False,indent=2)+'\n').encode();path.write_bytes(raw)
   row={'concept_key':old['concept_key'],'overview':'corrected'}
   with self.assertRaisesRegex(ValueError,'same_event_profile_conflict'):profiles.preserve_semantic_revision(root,path,old,row)
   self.assertFalse((path.parent/'历史版本').exists())
   row.update(supersedes_content_sha256='0'*64,revision_reason='remove obsolete workflow wording')
   with self.assertRaisesRegex(ValueError,'same_event_profile_conflict'):profiles.preserve_semantic_revision(root,path,old,row)
   row['supersedes_content_sha256']=old['content_sha256'];profiles.preserve_semantic_revision(root,path,old,row)
   saved=path.parent/'历史版本'/old['concept_key']/(old['content_sha256']+'.json');self.assertEqual(saved.read_bytes(),raw);self.assertEqual(path.read_bytes(),raw)
   profiles.preserve_semantic_revision(root,path,old,row)
 def test_invalid_predecessor_content_cannot_authorize_revision(self):
  old={'concept_key':'MATH-CONCEPT-fixture','content_sha256':'a'*64}
  with self.assertRaisesRegex(ValueError,'predecessor_invalid'):
   profiles.preserve_semantic_revision(Path('/unused'),Path('/unused/profile.json'),old,{'concept_key':old['concept_key'],'supersedes_content_sha256':'a'*64,'revision_reason':'correction'})
if __name__=='__main__':unittest.main()
