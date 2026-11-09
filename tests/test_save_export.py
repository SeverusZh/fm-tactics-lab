import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import desktop_coach_presets
import desktop_save_compat
import desktop_save_export
import desktop_save_mode
import fm27_fmf
import fm27_tactic_pool

SOURCE={'save_id':'0123456789abcdef','source':'C:/saves/career.fm','source_sha256':'a'*64,
        'date':'2027-01-15','build':'27.1.0'}
TAC_PLAN_HEADER=b'\x22'+struct.pack('<H',68)+b'\x1b'

def sample_plan(seed,size=96):
    base=hashlib.sha256(str(seed).encode()).digest()
    return TAC_PLAN_HEADER+(base*((size+len(base)-1)//len(base)))[:size]

def archive(seed,name='战术',size=96):
    return fm27_fmf.tactics_archive(sample_plan(seed,size),name)

def item(club_uid,club,target,tactic_name,payload,report=None):
    return {'club_uid':club_uid,'club':club,'target':target,'tactic_name':tactic_name,
            'payload':payload,'report':report or {'native_roundtrip_verified':True}}

class FmfPlanTests(unittest.TestCase):
    def test_roundtrip_preserves_plan_across_block_boundaries(self):
        for size in [1,7,8,100,65535,65536,65537,200000]:
            plan=sample_plan(size,size)
            self.assertEqual(fm27_fmf.tactics_plan(fm27_fmf.tactics_archive(plan,'测试战术')),plan)

    def test_rejects_invalid_archives(self):
        payload=archive(1)
        start=len(fm27_fmf.HEADER)+17;content=start+12
        cases=[('bytes', 'not bytes'),('short',payload[:20]),('magic',b'\x00'+payload[1:]),
               ('content',payload[:content]+bytes([payload[content]^1])+payload[content+1:]),
               ('truncated',payload[:-1])]
        for label,value in cases:
            with self.subTest(label=label),self.assertRaises(ValueError):
                fm27_fmf.tactics_plan(value)

    def test_rejects_declared_content_size_mismatch(self):
        payload=bytearray(archive(2));start=len(fm27_fmf.HEADER)+17
        struct.pack_into('<I',payload,start+5,len(sample_plan(2))+1)
        with self.assertRaises(ValueError):fm27_fmf.tactics_plan(bytes(payload))

class SafeComponentTests(unittest.TestCase):
    def test_replaces_windows_illegal_characters(self):
        value=desktop_save_export.safe_component('a<b>c:d"e/f\\g|h?i*j','球队1')
        self.assertFalse(any(c in value for c in '<>:"/\\|?*'))
        self.assertEqual(value,'a_b_c_d_e_f_g_h_i_j')

    def test_fallback_for_empty_or_traversal_names(self):
        for value in ['',None,'   ','...','..','/','..\\..']:
            self.assertTrue(desktop_save_export.safe_component(value,'球队9'))
        self.assertNotIn('/',desktop_save_export.safe_component('../../evil','球队1'))
        self.assertNotIn('\\',desktop_save_export.safe_component('..\\..\\evil','球队1'))

    def test_reserved_device_names_are_prefixed(self):
        for name in ['CON','con','PRN','NUL','COM1','LPT9','CON.fmf']:
            value=desktop_save_export.safe_component(name,'球队1')
            self.assertEqual(value[0],'_')
            self.assertNotIn(value.split('.',1)[0].casefold(),{'con','prn','aux','nul'})

    def test_trims_edges_and_limits_length(self):
        self.assertEqual(desktop_save_export.safe_component(' 战术. ','球队1'),'战术')
        self.assertLessEqual(len(desktop_save_export.safe_component('战术'*100,'球队1')),60)

class ExportWriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root=ROOT/'build/test-temp';cls.temp_root.mkdir(parents=True,exist_ok=True)

    def setUp(self):
        self.holder=tempfile.TemporaryDirectory(dir=self.temp_root);self.base=Path(self.holder.name)

    def tearDown(self):
        self.holder.cleanup()

    def test_writes_files_manifest_and_embedded_plans(self):
        items=[item(1,'甲队','stored:0','控球',archive(1)),
               item(1,'甲队','stored:1','反击',archive(2)),
               item(2,'乙队','coach:77','高压',archive(3))]
        result=desktop_save_export.write(self.base,SOURCE,items)
        root=Path(result['directory'])
        self.assertEqual(root.parent,self.base.resolve())
        self.assertRegex(root.name,r'^FM27存档战术-\d{8}-\d{6}$')
        self.assertEqual(result['profile'],'saved-tactic-export-v1')
        self.assertEqual(result['failures'],[])
        self.assertEqual(len(result['files']),3)
        self.assertTrue((root/'甲队'/'控球.fmf').is_file())
        self.assertTrue((root/'甲队'/'反击.fmf').is_file())
        self.assertTrue((root/'乙队'/'高压.fmf').is_file())
        self.assertTrue((root/'导出说明.txt').is_file())
        manifest=json.loads((root/'manifest.json').read_text(encoding='utf8'))
        self.assertEqual(manifest['profile'],result['profile'])
        self.assertEqual(manifest['source'],SOURCE)
        self.assertEqual(manifest['files'],result['files'])
        self.assertTrue(manifest['created']and manifest['notice'])
        plans={0:sample_plan(1),1:sample_plan(2),2:sample_plan(3)}
        for index,entry in enumerate(result['files']):
            written=(root/entry['file']).read_bytes()
            self.assertEqual(hashlib.sha256(written).hexdigest(),entry['sha256'])
            self.assertEqual(len(written),entry['size'])
            self.assertEqual(entry['plan_sha256'],hashlib.sha256(plans[index]).hexdigest())
            self.assertEqual(entry['plan_size'],len(plans[index]))
            self.assertEqual(fm27_fmf.tactics_plan(written),plans[index])
            self.assertTrue(entry['report']['native_roundtrip_verified'])
        self.assertEqual({e['target'] for e in result['files']},{'stored:0','stored:1','coach:77'})

    def test_duplicate_names_and_club_folders_are_deduplicated(self):
        items=[item(1,'同队','stored:0','Tactic',archive(1)),
               item(1,'同队','stored:1','tactic',archive(2)),
               item(1,'同队','stored:2','TACTIC',archive(3)),
               item(2,'同队','coach:9','Tactic',archive(4))]
        result=desktop_save_export.write(self.base,SOURCE,items)
        root=Path(result['directory'])
        self.assertTrue((root/'同队'/'Tactic.fmf').is_file())
        self.assertTrue((root/'同队'/'tactic2.fmf').is_file())
        self.assertTrue((root/'同队'/'TACTIC3.fmf').is_file())
        self.assertTrue((root/'同队2'/'Tactic.fmf').is_file())
        names=[e['file'] for e in result['files'] if e['club_uid']==1]
        self.assertEqual(len({name.casefold()for name in names}),3)

    def test_export_directory_gets_numeric_suffix(self):
        with mock.patch.object(desktop_save_export,'_stamp',return_value='20260101-120000'):
            first=desktop_save_export.write(self.base,SOURCE,[item(1,'甲队','stored:0','控球',archive(1))])
            second=desktop_save_export.write(self.base,SOURCE,[item(1,'甲队','stored:0','控球',archive(1))])
        self.assertEqual(Path(first['directory']).name,'FM27存档战术-20260101-120000')
        self.assertEqual(Path(second['directory']).name,'FM27存档战术-20260101-120000-2')

    def test_symlinked_export_directory_is_not_followed(self):
        if not hasattr(Path,'symlink_to'):self.skipTest('当前平台不支持符号链接')
        outside=self.base/'external';outside.mkdir()
        with mock.patch.object(desktop_save_export,'_stamp',return_value='20260101-130000'):
            try:(self.base/'FM27存档战术-20260101-130000').symlink_to(outside,target_is_directory=True)
            except OSError:self.skipTest('当前平台不允许创建符号链接')
            try:result=desktop_save_export.write(self.base,SOURCE,[item(1,'甲队','stored:0','控球',archive(1))])
            except OSError:self.skipTest('当前平台不允许创建符号链接')
        self.assertEqual(Path(result['directory']).name,'FM27存档战术-20260101-130000-2')
        self.assertEqual(list(outside.iterdir()),[])

    def test_rejects_invalid_payload_without_leaving_output(self):
        payload=bytearray(archive(1));payload[0]=0
        with self.assertRaises(ValueError):
            desktop_save_export.write(self.base,SOURCE,[item(1,'甲队','stored:0','控球',bytes(payload))])
        self.assertEqual(list(self.base.iterdir()),[])

    def test_rejects_more_than_max_files(self):
        items=[item(1,'甲队',f'stored:{i}',f'战术{i}',archive(i)) for i in range(desktop_save_export.MAX_FILES+1)]
        with self.assertRaises(ValueError):desktop_save_export.write(self.base,SOURCE,items)
        self.assertEqual(list(self.base.iterdir()),[])

    def test_rejects_missing_or_relative_directory(self):
        with self.assertRaises(ValueError):
            desktop_save_export.write(self.base/'missing',SOURCE,[item(1,'甲队','stored:0','控球',archive(1))])
        with self.assertRaises(ValueError):
            desktop_save_export.write('relative/path',SOURCE,[item(1,'甲队','stored:0','控球',archive(1))])

    def test_escaped_names_stay_inside_export_directory(self):
        items=[item(1,'..\\..\\逃逸','stored:0','../../evil',archive(1))]
        result=desktop_save_export.write(self.base,SOURCE,items)
        root=Path(result['directory']).resolve()
        self.assertEqual([p.name for p in self.base.iterdir()],[root.name])
        self.assertFalse((self.base.parent/'evil.fmf').exists())
        for path in root.rglob('*'):
            self.assertTrue(str(path.resolve()).startswith(str(root)))

    def test_cleans_up_when_writing_fails(self):
        real=desktop_save_export._atomic;calls=[]
        def failing(path,payload):
            calls.append(path)
            if len(calls)==2:raise OSError('磁盘写入失败')
            return real(path,payload)
        with mock.patch.object(desktop_save_export,'_atomic',side_effect=failing):
            with self.assertRaises(OSError):
                desktop_save_export.write(self.base,SOURCE,[item(1,'甲队','stored:0','控球',archive(1)),
                    item(1,'甲队','stored:1','反击',archive(2))])
        self.assertEqual(list(self.base.iterdir()),[])


class _Engine:
    def sha(self,path):return hashlib.sha256(str(path).encode()).hexdigest()

class _App:
    def __init__(self,root):
        self.RUNS=root/'runs';self.RUNS.mkdir(parents=True)
        self.NATIVE=root/'native';self.NATIVE.mkdir()
        self.desktop_engine=_Engine();self.ENGINE_COMPATIBILITY={'resource_fingerprint':'test'}

def tactic_cells():
    return [{'position':'GK'if index==0 else'DC','role':'GK'if index==0 else'DC','duty':'0',
             'instructions':{},'target_player':255,'target_position':0}for index in range(11)]

def preset_team(tactic_name='教练偏好预设 · 高位逼抢',extra='0',mentality=4):
    return {'name':'对手','tactic_name':tactic_name,'mentality':mentality,'instructions':{'1':0},
            'native_extra_team_bits':extra,'phases':[tactic_cells(),tactic_cells()]}

def pool_entry(name,extra='0'):
    return {'name':name,'weight':1,'tactic':fm27_tactic_pool.entry_from_team(preset_team(extra=extra))['tactic']}

def opponent(team_id,club_uid,name,preset_name,available=True,member=None):
    return {'key':f'coach:{team_id}','club_uid':club_uid,'name':name,'available':available,
            'member':member or f'original_installation_preset:{team_id}',
            'source':'教练偏好预设 · 王教练 · 高位逼抢','coach':{'preset_name':preset_name,'team_id':team_id}}

def league_report(opponents,failures=None,unrecovered=None,league=True,same_league_clubs=3):
    return {'opponents':opponents,'failures':failures or [],'unrecovered_clubs':unrecovered or [],
            'league':{'competition_id':17,'club_uids':[1,2,3,4]}if league else None,
            'same_league_clubs':same_league_clubs}

class SaveLibraryLeagueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root=ROOT/'build/test-temp';cls.temp_root.mkdir(parents=True,exist_ok=True)

    def setUp(self):
        self.holder=tempfile.TemporaryDirectory(dir=self.temp_root);self.root=Path(self.holder.name)
        self.app=_App(self.root);self.lib=desktop_save_mode.SaveLibrary(self.app)

    def tearDown(self):
        desktop_save_mode.dataset.cache_clear();self.holder.cleanup()

    def save(self):
        key='0123456789abcdef';folder=self.lib.root/key;folder.mkdir(parents=True)
        data={'schema':4,'source':SOURCE['source'],'source_sha256':SOURCE['source_sha256'],'date':SOURCE['date'],
              'build':SOURCE['build'],'tactics':[],'fixtures':[],'selections':[],'caches':[],'managed':[],
              'clubs':[{'uid':1,'name':'甲队','short_name':'甲','nation_id':14},
                       {'uid':2,'name':'乙队','short_name':'乙','nation_id':14},
                       {'uid':3,'name':'丙队','short_name':'丙','nation_id':20},
                       {'uid':4,'name':'丁队','short_name':'丁','nation_id':14}]}
        (folder/'dataset.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
        desktop_save_mode.dataset.cache_clear()
        return key,folder

    def test_league_library_composes_own_and_opponents(self):
        key,_=self.save()
        with mock.patch.object(self.lib,'begin_opponents',return_value={'status':'reading','stage':'正在读取同联赛教练偏好'}):
            self.assertEqual(self.lib.league_library(key,1),{'status':'reading','stage':'正在读取同联赛教练偏好'})
        with mock.patch.object(self.lib,'begin_opponents',return_value={'status':'error','stage':'读取失败'}):
            self.assertEqual(self.lib.league_library(key,1),{'status':'error','stage':'读取失败'})
        opponents=[opponent(77,2,'乙队','高位逼抢',member='original_installation_preset:3'),
                   opponent(88,3,'丙队','低位防守')]
        report=league_report(opponents,failures=[{'club_uid':4,'name':'丁队','error':'主教练缺失'}],
            unrecovered=[{'club_uid':4,'name':'丁队','reason':'教练偏好预设尚不可用'},
                         {'club_uid':5,'name':'戊队','reason':'教练偏好预设尚不可用'}])
        with mock.patch.object(self.lib,'begin_opponents',return_value={'status':'complete'}),\
             mock.patch.object(self.lib,'inspect_opponents',return_value=report):
            value=self.lib.league_library(key,1)
        self.assertEqual(value['status'],'complete')
        self.assertEqual(value['save'],{'id':key,'source':SOURCE['source'],'source_sha256':SOURCE['source_sha256'],
            'date':SOURCE['date'],'build':SOURCE['build']})
        self.assertEqual(value['own'],{'club_uid':1,'name':'甲','nation_id':14,'league_id':17,'club_count':4})
        self.assertEqual(value['teams'],[
            {'club_uid':2,'name':'乙队','key':'coach:77','tactic_name':'高位逼抢',
             'source':'教练偏好预设 · 王教练 · 高位逼抢','available':True,'member':'original_installation_preset:3'},
            {'club_uid':3,'name':'丙队','key':'coach:88','tactic_name':'低位防守',
             'source':'教练偏好预设 · 王教练 · 高位逼抢','available':True,'member':'original_installation_preset:88'}])
        self.assertEqual([failure['club_uid']for failure in value['failures']],[4,5])
        without_league={'opponents':opponents,'failures':[],'unrecovered_clubs':[],'league':None,'same_league_clubs':3}
        with mock.patch.object(self.lib,'begin_opponents',return_value={'status':'complete'}),\
             mock.patch.object(self.lib,'inspect_opponents',return_value=without_league):
            value=self.lib.league_library(key,1)
        self.assertEqual((value['own']['league_id'],value['own']['club_count']),(None,4))
        without_league['same_league_clubs']=0
        with mock.patch.object(self.lib,'begin_opponents',return_value={'status':'complete'}),\
             mock.patch.object(self.lib,'inspect_opponents',return_value=without_league):
            value=self.lib.league_library(key,1)
        self.assertEqual(value['own']['club_count'],3)

    def test_export_league_tactics_writes_available_and_records_failures(self):
        key,_=self.save()
        self.app.DEFAULT={'teams':[{'name':'甲','tactic_name':''},{'name':'乙','tactic_name':''}]}
        self.app.validate_scenario=lambda value:value
        exported=[]
        def export_fmf(data):
            exported.append(data)
            return {'file_base64':base64.b64encode(archive(99)).decode(),
                'report':{'native_roundtrip_verified':True}}
        self.app.export_fmf=export_fmf
        report=league_report([opponent(77,2,'乙队','高位逼抢'),opponent(88,3,'丙队','低位防守')],
            unrecovered=[{'club_uid':4,'name':'丁队','reason':'教练偏好预设尚不可用'}])
        def preset(lib,key,candidate):
            if candidate=='coach:88':raise ValueError('原装预设内容已改变')
            return preset_team()
        directory=self.root/'out';directory.mkdir()
        with mock.patch.object(self.lib,'inspect_opponents',return_value=report),\
             mock.patch.object(desktop_coach_presets,'preset_tactic',side_effect=preset):
            result=self.lib.export_league_tactics(key,1,str(directory))
        root=Path(result['directory'])
        self.assertEqual([(entry['club'],entry['tactic_name'])for entry in result['files']],[('乙队','高位逼抢')])
        self.assertEqual(fm27_fmf.tactics_plan((root/result['files'][0]['file']).read_bytes()),sample_plan(99))
        failures={(failure['club_uid'],failure['error'])for failure in result['failures']}
        self.assertIn((3,'原装预设内容已改变'),failures)
        self.assertIn((4,'教练偏好预设尚不可用'),failures)
        self.assertEqual(result['league'],{'league_id':17,'club_count':4})
        self.assertEqual(result['manifest']['source']['save_id'],key)
        self.assertEqual([(call['side'],call['scenario']['teams'][1]['name'])for call in exported],[(1,'对手')])
        empty=self.root/'empty';empty.mkdir()
        with mock.patch.object(self.lib,'inspect_opponents',return_value=report),\
             mock.patch.object(desktop_coach_presets,'preset_tactic',side_effect=ValueError('不可用')):
            with self.assertRaises(ValueError)as caught:
                self.lib.export_league_tactics(key,1,str(empty))
        self.assertIn('没有可导出',str(caught.exception))
        self.assertEqual(os.listdir(empty),[])
        for value in [None,'relative/path',str(self.root/'missing')]:
            with self.subTest(directory=value),self.assertRaises(ValueError):
                self.lib.export_league_tactics(key,1,value)

    def test_import_league_tactics_pool_dedupes_and_names_by_club(self):
        key,_=self.save()
        with mock.patch.object(self.lib,'begin_opponents',return_value={'status':'reading','stage':'读取中'}):
            self.assertEqual(self.lib.import_league_tactics_pool(key,1,{'teams':[]}),{'status':'reading','stage':'读取中'})
        entries=[{'name':'已有战术','weight':2,'tactic':pool_entry('已有战术','1')['tactic']}]
        scenario={'teams':[{'name':'甲'},{'name':'乙'}],
            'away_tactic_pool':{'profile':fm27_tactic_pool.PROFILE,'enabled':True,'entries':entries,
                'uniform':{'enabled':False,'attribute_value':12}}}
        original=copy.deepcopy(scenario)
        report=league_report([opponent(77,2,'乙队','高位逼抢'),opponent(88,3,'丙队','高位逼抢'),
                              opponent(99,4,'丁队','边路传中')],
            unrecovered=[{'club_uid':5,'name':'戊队','reason':'教练偏好预设尚不可用'}])
        preset_teams={'coach:77':preset_team(extra='1'),'coach:88':preset_team(extra='2'),
                      'coach:99':preset_team(extra='2')}
        self.app.validate_scenario=mock.Mock(side_effect=lambda value:value)
        with mock.patch.object(self.lib,'begin_opponents',return_value={'status':'complete'}),\
             mock.patch.object(self.lib,'inspect_opponents',return_value=report),\
             mock.patch.object(desktop_coach_presets,'preset_tactic',
                 side_effect=lambda lib,key,candidate:preset_teams[candidate]):
            value=self.lib.import_league_tactics_pool(key,1,scenario)
        self.assertEqual(value['status'],'complete')
        self.assertEqual(value['imported'],[{'club_uid':3,'club':'丙队','tactic_name':'高位逼抢'}])
        self.assertEqual((value['duplicates'],value['skipped_unavailable']),(2,1))
        pool=value['scenario']['away_tactic_pool']
        self.assertEqual([entry['name']for entry in pool['entries']],['已有战术','丙队'])
        self.assertEqual(pool['entries'][-1]['tactic']['native_extra_team_bits'],'2')
        self.assertEqual(pool['uniform'],{'enabled':False,'attribute_value':12})
        self.assertTrue(pool['enabled'])
        self.assertEqual([row['name']for row in value['pool']['entries']],['已有战术','丙队'])
        self.assertEqual(value['league'],{'league_id':17,'club_count':4})
        self.assertEqual(scenario,original)
        self.app.validate_scenario.assert_called_once()

    def test_import_league_tactics_pool_creates_default_pool(self):
        key,_=self.save()
        scenario={'teams':[{'name':'甲'},{'name':'乙'}]}
        self.app.validate_scenario=lambda value:value
        report=league_report([opponent(77,2,'乙队','高位逼抢')],unrecovered=[])
        with mock.patch.object(self.lib,'begin_opponents',return_value={'status':'complete'}),\
             mock.patch.object(self.lib,'inspect_opponents',return_value=report),\
             mock.patch.object(desktop_coach_presets,'preset_tactic',return_value=preset_team(extra='5')):
            value=self.lib.import_league_tactics_pool(key,1,scenario)
        pool=value['scenario']['away_tactic_pool']
        self.assertEqual((pool['enabled'],len(pool['entries'])),(False,1))
        self.assertEqual(pool['entries'][0]['name'],'乙队')
        self.assertEqual(value['imported'],[{'club_uid':2,'club':'乙队','tactic_name':'高位逼抢'}])
        self.assertEqual((value['duplicates'],value['skipped_unavailable']),(0,0))
        self.assertNotIn('away_tactic_pool',scenario)

    def test_import_league_tactics_pool_enforces_max_entries(self):
        key,_=self.save()
        entries=[{'name':f'已有{number}','weight':1,'tactic':pool_entry(f'已有{number}',str(number))['tactic']}
                 for number in range(fm27_tactic_pool.MAX_ENTRIES)]
        scenario={'teams':[{'name':'甲'},{'name':'乙'}],
            'away_tactic_pool':{'profile':fm27_tactic_pool.PROFILE,'enabled':False,'entries':entries,
                'uniform':{'enabled':True,'attribute_value':15}}}
        self.app.validate_scenario=lambda value:value
        report=league_report([opponent(77,2,'乙队','高位逼抢')],unrecovered=[])
        with mock.patch.object(self.lib,'begin_opponents',return_value={'status':'complete'}),\
             mock.patch.object(self.lib,'inspect_opponents',return_value=report),\
             mock.patch.object(desktop_coach_presets,'preset_tactic',return_value=preset_team(extra='999')):
            with self.assertRaises(ValueError)as caught:
                self.lib.import_league_tactics_pool(key,1,scenario)
        self.assertIn('最多保存',str(caught.exception))

class ReusableSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root=ROOT/'build/test-temp';cls.temp_root.mkdir(parents=True,exist_ok=True)

    def setUp(self):
        self.holder=tempfile.TemporaryDirectory(dir=self.temp_root);self.root=Path(self.holder.name)
        self.app=_App(self.root);self.lib=desktop_save_mode.SaveLibrary(self.app)

    def tearDown(self):
        desktop_save_mode.dataset.cache_clear();self.holder.cleanup()

    def test_requires_schema_4(self):
        digest='b'*64;folder=self.lib.root/'fedcba9876543210';folder.mkdir(parents=True)
        data={'source':SOURCE['source'],'source_sha256':digest,'reader_compatibility_profile':desktop_save_compat.PROFILE,
              'first_team_counts':{},'caches':[],'tactics':[],'clubs':[],'schema':3}
        self.lib.write(folder/'progress.json',{'status':'complete'})
        self.lib.write(folder/'dataset.json',data)
        self.assertIsNone(self.lib.reusable_source(digest))
        data['schema']=4
        self.lib.write(folder/'dataset.json',data)
        (folder/'player_index.json').write_text('{}',encoding='utf8');(folder/'rosters').mkdir()
        desktop_save_mode.dataset.cache_clear()
        self.assertEqual(self.lib.reusable_source(digest),folder)

if __name__=='__main__':
    unittest.main()
