import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
os.environ.setdefault('FM27_ENGINE_ROOT',str(ROOT/'build/test-temp'))
sys.path.insert(0,str(ROOT/'src'))
from desktop_warm_batch import DesktopWarmRunner

class WorkerSessionTests(unittest.TestCase):
 def setUp(self):
  root=ROOT/'build/test-temp';root.mkdir(parents=True,exist_ok=True)
  self.temp=tempfile.TemporaryDirectory(dir=root);self.addCleanup(self.temp.cleanup)
  self.root=Path(self.temp.name);(self.root/'fm27_native').mkdir()
  (self.root/'fm27_native/FM27Simulator.exe').write_bytes(b'worker-capability-fixture')
  DesktopWarmRunner._capabilities_cache.clear()
 def runner(self,body,code=0):
  result=subprocess.CompletedProcess([],code,json.dumps(body).encode(),b'')
  with patch('desktop_warm_batch.subprocess.run',return_value=result):return DesktopWarmRunner(self.root)
 def test_new_host_keeps_entire_lane_with_or_without_execution(self):
  runner=self.runner(dict(protocol=2,max_jobs=1000000,execution_context_reset=True,per_match_resource_release=True))
  lanes=[list(range(200)),list(range(199))]
  self.assertEqual(runner.session_size(lanes,True),200)
  self.assertEqual(runner.session_size(lanes,False),200)
 def test_legacy_host_preserves_execution_isolation(self):
  runner=self.runner({},79)
  self.assertEqual(runner.session_size([list(range(200))],True),1)
  self.assertEqual(runner.session_size([list(range(200))],False),64)
 def test_missing_cleanup_capability_cannot_enable_reuse(self):
  runner=self.runner(dict(protocol=2,max_jobs=1000000,execution_context_reset=True))
  self.assertFalse(runner.counted_sessions)
  self.assertEqual(runner.session_size([[1,2]],True),1)
 def test_invalid_job_limit_cannot_enable_reuse(self):
  for limit in (0,-1,'1000',True,1000001):
   DesktopWarmRunner._capabilities_cache.clear()
   runner=self.runner(dict(protocol=2,max_jobs=limit,execution_context_reset=True,per_match_resource_release=True))
   self.assertFalse(runner.counted_sessions,limit)
 def test_host_change_invalidates_capability_cache(self):
  self.runner({},79)
  (self.root/'fm27_native/FM27Simulator.exe').write_bytes(b'upgraded-worker')
  runner=self.runner(dict(protocol=2,max_jobs=1000,execution_context_reset=True,per_match_resource_release=True))
  self.assertTrue(runner.counted_sessions)

class WorkerResourceTests(unittest.TestCase):
 def test_high_core_machine_has_headroom_and_conservative_default(self):
  from fm27_batch import resource_limits
  result=resource_limits(24,14*1024**3)
  self.assertEqual(result['maximum'],256)
  self.assertEqual(result['resource_suggested_maximum'],8)
  self.assertEqual(result['recommended'],4)
 def test_cpu_and_current_free_memory_both_limit_parallelism(self):
  from fm27_batch import resource_limits
  self.assertEqual(resource_limits(24,5*1024**3)['resource_suggested_maximum'],3)
  self.assertEqual(resource_limits(8,32*1024**3)['resource_suggested_maximum'],4)
  self.assertEqual(resource_limits(2,1*1024**3)['resource_suggested_maximum'],1)

 def test_manual_limit_does_not_shrink_on_a_low_memory_machine(self):
  from fm27_batch import resource_limits
  result=resource_limits(2,1024**3)
  self.assertEqual(result['maximum'],256)
  self.assertEqual(result['recommended'],1)
