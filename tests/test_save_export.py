import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import desktop_coach_presets
import desktop_game_db_names
import desktop_real_generation
import desktop_real_library
import desktop_generation_protocol
import desktop_save_compat
import desktop_save_export
import desktop_save_mode
import desktop_static_plans
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

def item(club_uid,club,target,tactic_name,payload,coach='主教练',index=1,report=None):
    stem=f'{club}-{coach}-第{index}套战术'
    return {'club_uid':club_uid,'club':club,'coach':coach,'index':index,'name':stem,
            'target':target,'tactic_name':stem,'payload':payload,
            'report':report or {'native_roundtrip_verified':True}}

class FmfPlanTests(unittest.TestCase):
    def test_roundtrip_preserves_plan_across_block_boundaries(self):
        for size in [1,7,8,100,65535,65536,65537,200000]:
            plan=sample_plan(size,size)
            self.assertEqual(fm27_fmf.tactics_plan(fm27_fmf.tactics_archive(plan,'测试战术')),plan)

    def test_rejects_invalid_archives(self):
        payload=archive(1)
        start=len(fm27_fmf.HEADER)+17;content=start+12
        cases=[('bytes','not bytes'),('short',payload[:20]),('magic',b'\x00'+payload[1:]),
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

    def test_tactic_file_name_uses_club_coach_and_index(self):
        self.assertEqual(desktop_save_export.tactic_file_name('德比郡','韦恩·鲁尼',2),'德比郡-韦恩·鲁尼-第2套战术')
        self.assertEqual(desktop_save_export.tactic_file_name('','',0),'俱乐部-主教练-第1套战术')
        self.assertLessEqual(len(desktop_save_export.tactic_file_name('甲'*80,'乙'*80,1)),60)

class ExportWriteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root=ROOT/'build/test-temp';cls.temp_root.mkdir(parents=True,exist_ok=True)

    def setUp(self):
        self.holder=tempfile.TemporaryDirectory(dir=self.temp_root);self.base=Path(self.holder.name)

    def tearDown(self):
        self.holder.cleanup()

    def test_writes_flat_files_manifest_and_embedded_plans(self):
        items=[item(1,'甲队','stored:0','控球',archive(1),index=1),
               item(1,'甲队','stored:1','反击',archive(2),index=2),
               item(2,'乙队','coach:77','高压',archive(3),coach='乙帅')]
        result=desktop_save_export.write(self.base,SOURCE,items)
        root=Path(result['directory'])
        self.assertEqual(root.parent,self.base.resolve())
        self.assertRegex(root.name,r'^FM27存档战术-\d{8}-\d{6}$')
        self.assertEqual(result['profile'],'saved-tactic-export-v2')
        self.assertEqual(result['failures'],[])
        self.assertEqual(len(result['files']),3)
        self.assertTrue((root/'甲队-主教练-第1套战术.fmf').is_file())
        self.assertTrue((root/'甲队-主教练-第2套战术.fmf').is_file())
        self.assertTrue((root/'乙队-乙帅-第1套战术.fmf').is_file())
        self.assertTrue((root/'导出说明.txt').is_file())
        self.assertFalse(any(path.is_dir() for path in root.iterdir()))
        manifest=json.loads((root/'manifest.json').read_text(encoding='utf8'))
        self.assertEqual(manifest['profile'],result['profile'])
        self.assertEqual(manifest['source'],{'save_id':SOURCE['save_id'],'source_name':'career.fm',
            'source_sha256':SOURCE['source_sha256'],'date':SOURCE['date'],'build':SOURCE['build']})
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
            self.assertEqual((entry['club'],entry['coach'],entry['index']),([('甲队','主教练',1),('甲队','主教练',2),('乙队','乙帅',1)][index]))
        self.assertEqual({e['target'] for e in result['files']},{'stored:0','stored:1','coach:77'})

    def test_duplicate_file_names_are_deduplicated(self):
        same=item(1,'同队','stored:0','Tactic',archive(1))
        result=desktop_save_export.write(self.base,SOURCE,
            [same,{**same,'target':'stored:1','payload':archive(2)},{**same,'target':'stored:2','payload':archive(3)}])
        root=Path(result['directory'])
        self.assertTrue((root/'同队-主教练-第1套战术.fmf').is_file())
        self.assertTrue((root/'同队-主教练-第1套战术2.fmf').is_file())
        self.assertTrue((root/'同队-主教练-第1套战术3.fmf').is_file())
        self.assertEqual(len({entry['file'].casefold()for entry in result['files']}),3)

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
        items=[item(1,'..\\..\\逃逸','../../evil',archive(1),archive(1),coach='../../evil',index=1)]
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
                    item(1,'甲队','stored:1','反击',archive(2),index=2)])
        self.assertEqual(list(self.base.iterdir()),[])

class CoachVariantTests(unittest.TestCase):
    def catalog(self):
        return {'styles':[{'id':0,'style_code':100},{'id':1,'style_code':200}],
                'formations':[{'code':10,'positions':[1,2,3]},{'code':20,'positions':[4,5,6]}],
                'templates':[
                    {'index':0,'style_code':100,'name':'控球甲','phases':[[{'position':1},{'position':2},{'position':3}],
                        [{'position':1},{'position':2},{'position':3}]]},
                    {'index':1,'style_code':100,'name':'控球乙','phases':[[{'position':1},{'position':2},{'position':3}],
                        [{'position':1},{'position':2},{'position':3}]]},
                    {'index':2,'style_code':100,'name':'控球乙阵','phases':[[{'position':4},{'position':5},{'position':6}],
                        [{'position':4},{'position':5},{'position':6}]]}]}

    def test_primary_and_secondary_produce_distinct_presets(self):
        options=desktop_coach_presets.variants(self.catalog(),0,10,20)
        self.assertEqual([option['index']for option in options],[1,2])
        self.assertEqual(options[0]['preset']['index'],0)
        self.assertEqual(options[1]['preset']['index'],2)
        self.assertTrue(options[0]['exact']);self.assertTrue(options[1]['exact'])
        self.assertEqual((options[0]['formation_code'],options[1]['formation_code']),(10,20))

    def test_same_secondary_keeps_single_tactic(self):
        self.assertEqual(len(desktop_coach_presets.variants(self.catalog(),0,10,10)),1)
        self.assertEqual(len(desktop_coach_presets.variants(self.catalog(),0,10,99)),1)

    def test_unmapped_primary_is_rejected(self):
        with self.assertRaises(ValueError):desktop_coach_presets.variants(self.catalog(),0,99,10)

class _Engine:
    def sha(self,path):return hashlib.sha256(str(path).encode()).hexdigest()
    def require_available(self,compatibility):return None

class _AlternateEngine:
    def sha(self,path):return 'f'*64
    def require_available(self,compatibility):return None

class _App:
    def __init__(self,root):
        self.RUNS=root/'runs';self.RUNS.mkdir(parents=True)
        self.NATIVE=root/'native';self.NATIVE.mkdir()
        self.desktop_engine=_Engine();self.ENGINE_COMPATIBILITY={'resource_fingerprint':'test'}
    def integer(self,value,low,high,label):
        if type(value)is not int or not low<=value<=high:raise ValueError(label)
        return value

def tactic_cells():
    return [{'position':'GK'if index==0 else'DC','role':'GK'if index==0 else'DC','duty':'0',
             'instructions':{},'target_player':255,'target_position':0}for index in range(11)]

def preset_team(extra='0'):
    return {'name':'对手','tactic_name':'教练偏好预设','mentality':4,'instructions':{'1':0},
            'native_extra_team_bits':extra,'phases':[tactic_cells(),tactic_cells()]}


def generated_team(extra='0'):
    team=preset_team(extra)
    team['players']=[{'name':f'生成球员{index}','native_id':index,'source_uid':600+index,
        'attributes':[10]*69,'native_profile':{}}for index in range(23)]
    team.update(lineup=list(range(11)),roster_size=23,captains=[],takers={})
    return team

class SaveLibraryLeagueTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root=ROOT/'build/test-temp';cls.temp_root.mkdir(parents=True,exist_ok=True)

    def setUp(self):
        self.holder=tempfile.TemporaryDirectory(dir=self.temp_root);self.root=Path(self.holder.name)
        self.app=_App(self.root);self.lib=desktop_save_mode.SaveLibrary(self.app)
        self.names=mock.patch.object(desktop_game_db_names,'resolve',
            return_value={'competitions':{101:'测试甲级联赛',102:'测试乙级联赛'},
                          'nations':{5:'英格兰',6:'法国'},'source':'game_db'})
        self.names.start()

    def tearDown(self):
        self.names.stop();desktop_save_mode.dataset.cache_clear();self.holder.cleanup()

    def save(self):
        key='0123456789abcdef';folder=self.lib.root/key;folder.mkdir(parents=True)
        data={'schema':5,'source':SOURCE['source'],'source_sha256':SOURCE['source_sha256'],'date':SOURCE['date'],
              'build':SOURCE['build'],'tactics':[],'fixtures':[],'selections':[],'caches':[],
              'managed':[{'club_uid':1}],
              'clubs':[{'uid':1,'name':'甲队','short_name':'甲','nation_id':14}],
              'leagues':[{'key':'17:200:2026','competition_id':17,'stage_id':200,'season':2026,
                          'club_uids':[1,2,3,4],'fixture_count':24,'first_date':'2026-08-01','last_date':'2027-05-01'}],
              'league_clubs':{'1':{'name':'甲队','short_name':'甲','nation_id':14,'first_team_id':11,'club_unique_id':101},
                              '2':{'name':'乙队','short_name':'乙','nation_id':14,'first_team_id':12,'club_unique_id':102},
                              '3':{'name':'丙队','short_name':'丙','nation_id':20,'first_team_id':13,'club_unique_id':103},
                              '4':{'name':'丁队','short_name':'丁','nation_id':14,'first_team_id':14,'club_unique_id':104}},
              'nations':{'14':5,'20':6},'competitions':{'17':101}}
        (folder/'dataset.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
        self.lib.check_binding(folder)
        desktop_save_mode.dataset.cache_clear()
        return key,folder

    def team(self,club_uid,name,variants=((1,10,True),(2,20,True))):
        return {'club_uid':club_uid,'name':name,'coach_name':f'{name}主教练','available':True,
                'variants':[{'index':index,'preset_index':index,'preset_sha256':hashlib.sha256(str(index).encode()).hexdigest(),
                             'preset_name':f'预设{index}','formation':f'阵型{code}','formation_code':code,'exact':exact,
                             'position_difference':0}for index,code,exact in variants],'error':None}

    def test_league_catalog_names_leagues_and_nations(self):
        key,_=self.save()
        catalog=self.lib.league_catalog(key)
        self.assertEqual(catalog['name_source'],'game_db')
        self.assertEqual(catalog['save'],{'id':key,'source':SOURCE['source'],'date':SOURCE['date'],'build':SOURCE['build']})
        self.assertEqual(catalog['leagues'],[{'key':'17:200:2026','competition_id':17,'name':'测试甲级联赛',
            'nation':'英格兰','club_count':4,'season':2026,'own':True,
            'first_date':'2026-08-01','last_date':'2027-05-01'}])

    def test_league_catalog_falls_back_to_numbers_without_game_db_names(self):
        key,_=self.save()
        self.names.stop()
        with mock.patch.object(desktop_game_db_names,'resolve',
                return_value={'competitions':{},'nations':{},'source':'unavailable','detail':'missing'}):
            catalog=self.lib.league_catalog(key)
        self.assertEqual(catalog['name_source'],'unavailable')
        self.assertEqual([(row['name'],row['nation'])for row in catalog['leagues']],
            [('联赛 #17',None)])

    def test_league_catalog_requires_new_cache(self):
        key,folder=self.save()
        data=json.loads((folder/'dataset.json').read_text(encoding='utf8'));data.pop('leagues')
        (folder/'dataset.json').write_text(json.dumps(data),encoding='utf8');desktop_save_mode.dataset.cache_clear()
        with self.assertRaises(ValueError):self.lib.league_catalog(key)

    def test_league_library_lists_teams_and_variants(self):
        key,_=self.save()
        ensured={'teams':[self.team(2,'乙队'),self.team(3,'丙队')],'failures':[{'club_uid':4,'name':'丁队','error':'主教练缺失'}]}
        with mock.patch.object(desktop_coach_presets,'ensure',return_value=ensured)as ensure:
            self.lib.build_league_report(key,'17:200:2026')
        ensure.assert_called_once()
        self.assertEqual(ensure.call_args.kwargs['clubs'],[2,3,4])
        value=self.lib.league_library(key,'17:200:2026')
        self.assertEqual(value['status'],'complete')
        self.assertEqual(value['league']['name'],'测试甲级联赛')
        self.assertEqual([(row['club_uid'],row['coach_name'],row['available'])for row in value['teams']],
            [(4,None,False),(3,'丙队主教练',True),(2,'乙队主教练',True)])
        self.assertEqual([variant['index']for variant in next(row for row in value['teams']if row['club_uid']==2)['variants']],[1,2])
        self.assertEqual(value['failures'],[{'club_uid':4,'name':'丁队','error':'主教练缺失'}])

    def test_export_names_files_by_club_coach_and_index(self):
        key,_=self.save()
        ensured={'teams':[self.team(2,'乙队'),self.team(3,'丙队')],'failures':[{'club_uid':4,'name':'丁队','error':'主教练缺失'}]}
        directory=self.root/'out';directory.mkdir()
        self.app.DEFAULT={'teams':[{'name':'甲'},{'name':'乙'}]}
        self.app.validate_scenario=lambda value:value
        with mock.patch.object(desktop_coach_presets,'ensure',return_value=ensured),\
             mock.patch.object(self.lib,'preset_plan',side_effect=lambda key,index,sha:sample_plan(index)):
            result=self.lib.export_league_tactics(key,'17:200:2026',str(directory))
        root=Path(result['directory'])
        self.assertEqual(sorted(entry['file']for entry in result['files']),
            ['丙队-丙队主教练-第1套战术.fmf','丙队-丙队主教练-第2套战术.fmf',
             '乙队-乙队主教练-第1套战术.fmf','乙队-乙队主教练-第2套战术.fmf'])
        self.assertEqual(len(result['failures']),1)
        self.assertEqual(result['failures'][0]['club_uid'],4)
        self.assertEqual(result['league']['name'],'测试甲级联赛')
        for entry in result['files']:
            self.assertEqual(fm27_fmf.tactics_plan((root/entry['file']).read_bytes()),sample_plan(entry['index']))
            self.assertEqual((entry['club'],entry['coach'],entry['index']),
                (entry['file'].split('-')[0],entry['file'].split('-')[1],1 if '第1套' in entry['file']else 2))
        with mock.patch.object(desktop_coach_presets,'ensure',return_value={'teams':[],'failures':[]}):
            with self.assertRaises(ValueError)as caught:
                self.lib.export_league_tactics(key,'17:200:2026',str(directory))
        self.assertIn('没有可导出',str(caught.exception))

    def test_export_requires_directory(self):
        key,_=self.save()
        with mock.patch.object(desktop_coach_presets,'ensure',return_value={'teams':[self.team(2,'乙队')],'failures':[]}):
            for value in [None,'relative/path',str(self.root/'missing')]:
                with self.subTest(directory=value),self.assertRaises(ValueError):
                    self.lib.export_league_tactics(key,'17:200:2026',value)

    def test_preset_plan_is_cached_per_installation_preset(self):
        key,_=self.save()
        plan=sample_plan(7)
        exports=[]
        def export_fmf(data):
            exports.append(data)
            return {'file_base64':base64.b64encode(fm27_fmf.tactics_archive(plan,'FM27 预设战术')).decode(),
                    'report':{'native_roundtrip_verified':True,'sha256':'c'*64}}
        self.app.export_fmf=export_fmf
        self.app.DEFAULT={'teams':[{'name':'甲'},{'name':'乙'}]}
        self.app.validate_scenario=lambda value:value
        with mock.patch.object(desktop_coach_presets,'preset_by_index_team',return_value=preset_team()):
            first=self.lib.preset_plan(key,1,'d'*64)
            second=self.lib.preset_plan(key,1,'d'*64)
        self.assertEqual(first,plan);self.assertEqual(second,plan);self.assertEqual(len(exports),1)
        self.assertEqual(exports[0]['name'],'FM27 预设战术')

    def test_import_pool_keeps_duplicates_and_names_by_tactic(self):
        key,_=self.save()
        scenario={'teams':[{'name':'甲'},{'name':'乙'}]}
        self.app.validate_scenario=lambda value:value
        ensured={'teams':[self.team(2,'乙队',variants=((1,10,True),)),self.team(3,'丙队',variants=((1,10,True),))],'failures':[]}
        with mock.patch.object(desktop_coach_presets,'ensure',return_value=ensured),\
             mock.patch.object(desktop_coach_presets,'preset_by_index_team',return_value=preset_team(extra='3')):
            value=self.lib.import_league_tactics_pool(key,'17:200:2026',scenario)
        pool=value['scenario']['away_tactic_pool']
        self.assertEqual([entry['name']for entry in pool['entries']],
            ['丙队-丙队主教练-第1套战术','乙队-乙队主教练-第1套战术'])
        self.assertEqual(len(pool['entries']),2)
        self.assertEqual(value['imported'],[{'club_uid':3,'club':'丙队','coach':'丙队主教练','index':1,
            'source':'coach_preset','venue':None,'label':None,'name':'丙队-丙队主教练-第1套战术'},
            {'club_uid':2,'club':'乙队','coach':'乙队主教练','index':1,
            'source':'coach_preset','venue':None,'label':None,'name':'乙队-乙队主教练-第1套战术'}])
        self.assertNotIn('away_tactic_pool',scenario)
        with mock.patch.object(desktop_coach_presets,'ensure',return_value=ensured),\
             mock.patch.object(desktop_coach_presets,'preset_by_index_team',return_value=preset_team(extra='3')):
            again=self.lib.import_league_tactics_pool(key,'17:200:2026',value['scenario'])
        self.assertEqual(len(again['scenario']['away_tactic_pool']['entries']),4)

    def test_import_pool_enforces_capacity_before_adding(self):
        key,_=self.save()
        entries=[{'name':f'已有{number}','weight':1,'tactic':fm27_tactic_pool.entry_from_team(preset_team(),name=f'已有{number}')['tactic']}
                 for number in range(fm27_tactic_pool.MAX_ENTRIES)]
        scenario={'teams':[{'name':'甲'},{'name':'乙'}],
            'away_tactic_pool':{'profile':fm27_tactic_pool.PROFILE,'enabled':False,'entries':entries,
                'uniform':{'enabled':True,'attribute_value':15}}}
        self.app.validate_scenario=lambda value:value
        ensured={'teams':[self.team(2,'乙队',variants=((1,10,True),))],'failures':[]}
        with mock.patch.object(desktop_coach_presets,'ensure',return_value=ensured),\
             mock.patch.object(desktop_coach_presets,'preset_by_index_team',return_value=preset_team()):
            with self.assertRaises(ValueError)as caught:
                self.lib.import_league_tactics_pool(key,'17:200:2026',scenario)
        self.assertIn('最多保存',str(caught.exception))
        self.assertEqual(len(scenario['away_tactic_pool']['entries']),fm27_tactic_pool.MAX_ENTRIES)

    def test_pool_import_attaches_real_save_rosters(self):
        key,_=self.save()
        scenario={'teams':[{'name':'甲'},{'name':'乙'}]}
        self.app.validate_scenario=lambda value:value
        ensured={'teams':[self.team(2,'乙队',variants=((1,10,True),)),self.team(3,'丙队',variants=((1,10,True),))],'failures':[]}
        def fake_roster(lib,key,club,team,preferred=()):
            team['players']=[{'name':f'队{club}球员{index}','native_id':index,'attributes':[10]*69,
                'source_uid':club*100+index}for index in range(23)]
            team.update(lineup=list(range(11)),roster_size=23,captains=[],takers={})
            return team
        with mock.patch.object(self.lib,'ensure_rosters'),\
             mock.patch.object(desktop_coach_presets,'ensure',return_value=ensured),\
             mock.patch.object(desktop_coach_presets,'preset_by_index_team',return_value=preset_team()),\
             mock.patch.object(desktop_static_plans,'roster',side_effect=fake_roster):
            value=self.lib.import_league_tactics_pool(key,'17:200:2026',scenario)
        self.assertEqual(value['roster_failures'],[])
        for entry in value['scenario']['away_tactic_pool']['entries']:
            roster=entry['roster']
            self.assertEqual(roster['roster_size'],23)
            self.assertEqual(roster['lineup'],list(range(11)))
            self.assertEqual(len(roster['players']),23)
            self.assertTrue(all(player['attributes']==[10]*69 for player in roster['players']))
        self.assertEqual({entry['roster']['club_uid']for entry in value['scenario']['away_tactic_pool']['entries']},{2,3})

    def test_pool_import_keeps_tactics_when_roster_read_fails(self):
        key,_=self.save()
        scenario={'teams':[{'name':'甲'},{'name':'乙'}]}
        self.app.validate_scenario=lambda value:value
        ensured={'teams':[self.team(2,'乙队',variants=((1,10,True),))],'failures':[]}
        with mock.patch.object(self.lib,'ensure_rosters',side_effect=ValueError('名单读取失败')),\
             mock.patch.object(desktop_coach_presets,'ensure',return_value=ensured),\
             mock.patch.object(desktop_coach_presets,'preset_by_index_team',return_value=preset_team()),\
             mock.patch.object(desktop_static_plans,'roster',side_effect=ValueError('名单读取失败')):
            value=self.lib.import_league_tactics_pool(key,'17:200:2026',scenario)
        self.assertEqual(len(value['imported']),1)
        self.assertEqual(len(value['scenario']['away_tactic_pool']['entries']),1)
        self.assertNotIn('roster',value['scenario']['away_tactic_pool']['entries'][0])
        self.assertEqual(len(value['roster_failures']),2)

    def test_pool_import_disables_real_mode_when_new_entries_lack_rosters(self):
        key,_=self.save()
        entry=fm27_tactic_pool.entry_from_team(preset_team(),name='已有真实战术')
        entry['roster']={'club_uid':2,'club':'乙队','coach':'乙队主教练','source':'coach_preset',
            'roster_size':11,'lineup':list(range(11)),
            'players':[{'name':f'乙队球员{index}','source_uid':900+index,'attributes':[10]*69,
                'native_profile':{}}for index in range(11)]}
        scenario={'teams':[{'name':'甲'},{'name':'乙'}],
            'away_tactic_pool':{'profile':fm27_tactic_pool.PROFILE,'enabled':True,'entries':[entry],
                'uniform':{'enabled':True,'attribute_value':15},'real':{'enabled':True},
                'rotation':{'enabled':False,'rounds':1}}}
        self.app.validate_scenario=lambda value:value
        ensured={'teams':[self.team(3,'丙队',variants=((1,10,True),))],'failures':[]}
        with mock.patch.object(self.lib,'ensure_rosters',side_effect=ValueError('名单读取失败')),\
             mock.patch.object(desktop_coach_presets,'ensure',return_value=ensured),\
             mock.patch.object(desktop_coach_presets,'preset_by_index_team',return_value=preset_team()),\
             mock.patch.object(desktop_static_plans,'roster',side_effect=ValueError('名单读取失败')):
            value=self.lib.import_league_tactics_pool(key,'17:200:2026',scenario)
        self.assertTrue(value['real_disabled'])
        pool=value['scenario']['away_tactic_pool']
        self.assertFalse(pool['real']['enabled'])
        self.assertEqual(pool['players'] if 'players'in pool else fm27_tactic_pool.summary(pool)['players'],'uniform')
        self.assertNotIn('roster',pool['entries'][1])
        self.assertEqual(len(value['imported']),1)

    def test_apply_roster_overwrites_home_squad_and_keeps_tactics(self):
        key,folder=self.save()
        data=json.loads((folder/'dataset.json').read_text(encoding='utf8'))
        data['clubs'].append({'uid':2,'name':'乙队','short_name':'乙','nation_id':14})
        (folder/'dataset.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
        desktop_save_mode.dataset.cache_clear()
        (folder/'rosters').mkdir()
        people=[{'unique_id':300+index,'name':f'乙队球员{index}','club_uid':2,'team_slot':0,
            'positions':{},'ability':{'current':100+index}}for index in range(23)]
        (folder/'rosters'/'2.json').write_text(json.dumps(people,ensure_ascii=False),encoding='utf8')
        scenario={'teams':[{'name':'主队','tactic_name':'当前战术','mentality':3,
            'players':[{'name':'旧球员','native_id':index,'attributes':[9]*69,'source_uid':300+index}for index in range(23)],
            'lineup':list(range(11)),'roster_size':11,'captains':[5],'takers':{'penalties':[3]},
            'setpieces':{'role_priorities':{'penalties':[4]}}},{'name':'客队'}]}
        self.app.validate_scenario=lambda value:value
        def fake_roster(lib,key,club,team,preferred=()):
            for index in range(23):
                team['players'][index].update(name=f'乙队球员{index}',source_uid=300+index,
                    attributes=[10]*15+[50]*54,native_profile={'current_ability':100+index})
            team.update(lineup=list(range(11)),roster_size=23,captains=[],takers={})
            return team
        with mock.patch.object(desktop_static_plans,'roster',side_effect=fake_roster),\
             mock.patch.object(self.lib,'player_values',side_effect=lambda person:([10]*15+[50]*54,{'current_ability':person['unique_id']%100})):
            result=self.lib.apply_roster(key,2,scenario)
        home=result['scenario']['teams'][0]
        self.assertEqual(home['name'],'主队')
        self.assertEqual(home['tactic_name'],'当前战术')
        self.assertEqual(home['roster_size'],23)
        self.assertEqual(home['lineup'],list(range(11)))
        self.assertEqual(len(home['squad']),23)
        self.assertEqual([player['source_uid']for player in home['squad']],list(range(300,323)))
        self.assertEqual(home['squad'][0]['initial_attributes'],[10]*15+[50]*54)
        self.assertEqual([player['name']for player in home['players'][:2]],['乙队球员0','乙队球员1'])
        self.assertEqual(home['captains'],[5])
        self.assertEqual(home['takers'],{'penalties':[3]})
        self.assertEqual(home['setpieces']['role_priorities'],{'penalties':[4]})
        self.assertEqual(result['source'],{'club_uid':2,'club':'乙','roster_count':23,'match_roster_count':23,
            'notice':'主队球员名单与属性已覆盖为该存档球队的当前一线队；战术、定位球套路与球队名称保持不变。'})

    def wait_league(self,key,status,timeout=5):
        deadline=time.time()+timeout
        while time.time()<deadline:
            value=self.lib.league_library(key,'17:200:2026')
            if value.get('status')==status:return value
            time.sleep(0.01)
        raise AssertionError('league status timeout')

    def test_league_read_retries_after_transient_failure(self):
        key,_=self.save()
        ensured={'teams':[self.team(2,'乙队'),self.team(3,'丙队')],
            'failures':[{'club_uid':4,'name':'丁队','error':'主教练缺失'}]}
        with mock.patch.object(desktop_coach_presets,'ensure',side_effect=ValueError('临时失败')):
            self.assertEqual(self.lib.league_library(key,'17:200:2026')['status'],'reading')
            self.assertEqual(self.wait_league(key,'error')['status'],'error')
        with mock.patch.object(desktop_coach_presets,'ensure',return_value=ensured):
            self.assertEqual(self.lib.league_library(key,'17:200:2026')['status'],'reading')
            self.assertEqual(self.wait_league(key,'complete')['status'],'complete')

    def test_selection_skips_incomplete_club_index(self):
        index={'league_clubs':{'2':{'name':'乙队','first_team_id':12},'3':{'name':'丙队'}}}
        rows=desktop_coach_presets._selection(None,index,[2,3])
        self.assertEqual([row['uid']for row in rows],[2])
        with self.assertRaises(ValueError):desktop_coach_presets._selection(None,{'league_clubs':{}},[2])

    def test_preset_index_team_verifies_expected_sha(self):
        key,_=self.save()
        catalog={'styles':[],'formations':[],
            'templates':[{'index':0,'style_code':0,'name':'预设','phases':[[],[]]}],'binding':{}}
        with mock.patch.object(desktop_coach_presets,'assets',return_value=catalog),\
             mock.patch.object(desktop_coach_presets,'_preset_team',return_value={'name':'甲'}):
            expected=desktop_coach_presets.digest(catalog['templates'][0])
            self.assertEqual(desktop_coach_presets.preset_by_index_team(self.lib,key,0,'队',expected),
                {'name':'甲'})
            with self.assertRaises(ValueError):
                desktop_coach_presets.preset_by_index_team(self.lib,key,0,'队','0'*64)

    def test_start_rejects_while_real_generation_runs(self):
        source=self.root/'save.fm';source.write_bytes(b'save')
        key,_=self.save()
        self.lib.real_active={'key':key,'league':'17:200:2026','token':'t'}
        with self.assertRaises(ValueError)as caught:self.lib.start(str(source))
        self.assertIn('真实AI战术',str(caught.exception))

class RealGenerationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root=ROOT/'build/test-temp';cls.temp_root.mkdir(parents=True,exist_ok=True)

    def setUp(self):
        self.holder=tempfile.TemporaryDirectory(dir=self.temp_root);self.root=Path(self.holder.name)
        self.app=_App(self.root);self.lib=desktop_save_mode.SaveLibrary(self.app)
        self.names=mock.patch.object(desktop_game_db_names,'resolve',
            return_value={'competitions':{101:'测试甲级联赛',102:'测试乙级联赛'},'nations':{5:'英格兰'},'source':'game_db'})
        self.names.start()
        self.key='0123456789abcdef';folder=self.lib.root/self.key;folder.mkdir(parents=True)
        data={'schema':5,'source':SOURCE['source'],'source_sha256':SOURCE['source_sha256'],'date':SOURCE['date'],
              'build':SOURCE['build'],'tactics':[],'fixtures':[],'selections':[],'caches':[],'managed':[{'club_uid':1}],
              'clubs':[{'uid':1,'name':'甲队','short_name':'甲','nation_id':14}],
              'leagues':[{'key':'17:200:2026','competition_id':17,'stage_id':200,'season':2026,
                          'club_uids':[1,2,3],'fixture_count':12,'first_date':'2026-08-01','last_date':'2027-05-01'},
                         {'key':'18:300:2026','competition_id':18,'stage_id':300,'season':2026,
                          'club_uids':[2,3],'fixture_count':2,'first_date':'2026-08-01','last_date':'2027-05-01'}],
              'league_clubs':{'1':{'name':'甲队','short_name':'甲','nation_id':14,'first_team_id':11,'club_unique_id':101},
                              '2':{'name':'乙队','short_name':'乙','nation_id':14,'first_team_id':12,'club_unique_id':102},
                              '3':{'name':'丙队','short_name':'丙','nation_id':14,'first_team_id':13,'club_unique_id':103}},
              'nations':{'14':5},'competitions':{'17':101,'18':102}}
        (folder/'dataset.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
        self.lib.check_binding(folder);desktop_save_mode.dataset.cache_clear()
        self.directory=self.root/'out';self.directory.mkdir()
        self.plan=sample_plan(11)
        self.app.DEFAULT={'teams':[{'name':'甲','players':[]},{'name':'乙','players':[]}]}
        self.app.validate_scenario=lambda value:value
        def export_fmf(data):
            return {'file_base64':base64.b64encode(fm27_fmf.tactics_archive(self.plan,data['name'])).decode(),
                    'report':{'native_roundtrip_verified':True,'sha256':'c'*64}}
        self.app.export_fmf=export_fmf
        self.preview_calls=[]

    def tearDown(self):
        self.names.stop();desktop_save_mode.dataset.cache_clear();self.holder.cleanup()

    def result(self,club_uid,venue):
        return {'team':{'name':f'队{club_uid}','players':[],'roster_size':11,'tactic_name':f'真实-{club_uid}-{venue}'},
            'native_plan':{'mentality':5,'team_bits':'00'*16,'lineup_source_uids':list(range(11))},
            'venue':venue,'seed':0,'payload_sha256':'a'*64,'config_sha256':('b'*64),
            'own_club':1,'opponent_club':club_uid,'own_coach':'甲帅','opponent_coach':f'教练{club_uid}',
            'own_roster':list(range(100,123)),'opponent_roster':list(range(club_uid*100,club_uid*100+23))}

    def patches(self):
        def preview(lib,key,own,opponent,venue='H',seed=0,prepared=None):
            self.preview_calls.append((opponent,venue))
            return self.result(opponent,venue)
        return [mock.patch.object(desktop_real_generation,'ensure',return_value={'inputs':{},'staff':{}}),
                mock.patch.object(desktop_real_generation,'preview',side_effect=preview)]

    def wait_complete(self,timeout=15):
        deadline=time.time()+timeout
        while time.time()<deadline:
            state=self.lib.real_generation_status(self.key,'17:200:2026')
            if state.get('status')!='reading':return state
            time.sleep(0.02)
        raise AssertionError('generation timeout')

    def test_batch_generates_two_contexts_per_opponent_and_reports_progress(self):
        started=self.patches()
        for patch in started:patch.start();self.addCleanup(patch.stop)
        state=self.lib.start_real_generation(self.key,'17:200:2026')
        self.assertEqual(state['status'],'reading');self.assertEqual(state['total'],4)
        complete=self.wait_complete()
        self.assertEqual(complete['status'],'complete')
        self.assertEqual(complete['count'],2);self.assertEqual(complete['variant_count'],4)
        self.assertEqual(sorted(self.preview_calls),[(2,'A'),(2,'H'),(3,'A'),(3,'H')])
        library=desktop_real_library.load(self.lib,self.key,'17:200:2026')
        self.assertIsNotNone(library)
        self.assertEqual(library['source_sha256'],SOURCE['source_sha256'])
        self.assertEqual(library['own_club'],1)
        teams={row['club_uid']:row for row in library['teams']}
        self.assertEqual(sorted(teams),[2,3])
        self.assertEqual([variant['venue']for variant in desktop_real_library.variants(teams[2])],['A','H'])
        self.assertTrue(all(('主场战术'in variant['name'])or('客场战术'in variant['name'])for variant in desktop_real_library.variants(teams[2])))
        self.assertEqual(len({variant['plan_sha256']for variant in desktop_real_library.variants(teams[2])}),1)
        again=self.lib.start_real_generation(self.key,'17:200:2026')
        self.assertEqual(again['status'],'complete')
        self.assertEqual(len(self.preview_calls),4)

    def test_force_regenerates_existing_variants(self):
        started=self.patches()
        for patch in started:patch.start();self.addCleanup(patch.stop)
        self.lib.start_real_generation(self.key,'17:200:2026');self.wait_complete()
        self.assertEqual(len(self.preview_calls),4)
        again=self.lib.start_real_generation(self.key,'17:200:2026',force=True)
        self.assertEqual(again['status'],'reading');self.assertEqual(again['total'],4)
        self.wait_complete()
        self.assertEqual(len(self.preview_calls),8)

    def test_single_team_generation_merges_into_library(self):
        started=self.patches()
        for patch in started:patch.start();self.addCleanup(patch.stop)
        value=self.lib.generate_real_team(self.key,'17:200:2026',2)
        self.assertEqual(value['status'],'complete');self.assertEqual(value['variant_count'],2)
        self.assertEqual(sorted(self.preview_calls),[(2,'A'),(2,'H')])
        library=desktop_real_library.load(self.lib,self.key,'17:200:2026')
        self.assertEqual([row['club_uid']for row in library['teams']],[2])

    def test_export_uses_generated_library(self):
        started=self.patches()
        for patch in started:patch.start();self.addCleanup(patch.stop)
        self.lib.start_real_generation(self.key,'17:200:2026');self.wait_complete()
        with mock.patch.object(desktop_real_generation,'team_from_plan',return_value={'name':'队2'}):
            result=self.lib.export_league_tactics(self.key,'17:200:2026',str(self.directory))
        self.assertEqual(result['source'],'real_ai')
        self.assertEqual(result['profile'],desktop_save_export.REAL_PROFILE)
        self.assertEqual(len(result['files']),4)
        self.assertTrue(all(('主场战术'in entry['file'])or('客场战术'in entry['file'])for entry in result['files']))
        self.assertRegex(Path(result['directory']).name,r'^FM27真实AI战术-')
        for entry in result['files']:
            self.assertEqual(fm27_fmf.tactics_plan((Path(result['directory'])/entry['file']).read_bytes()),self.plan)
            self.assertEqual(entry['report']['source'],'original_engine_generation')
            self.assertIn(entry['report']['venue'],('H','A'))
        notice=(Path(result['directory'])/'导出说明.txt').read_text(encoding='utf8')
        self.assertIn('对手主场、对手客场',notice);self.assertIn('career.fm',notice);self.assertNotIn('C:/saves',notice)

    def test_pool_import_uses_generated_library(self):
        started=self.patches()
        for patch in started:patch.start();self.addCleanup(patch.stop)
        self.lib.start_real_generation(self.key,'17:200:2026');self.wait_complete()
        scenario={'teams':[{'name':'甲'},{'name':'乙'}]}
        self.app.validate_scenario=lambda value:value
        with mock.patch.object(desktop_real_generation,'team_from_plan',return_value=generated_team(extra='3')):
            value=self.lib.import_league_tactics_pool(self.key,'17:200:2026',scenario)
        self.assertEqual(value['source'],'real_ai')
        self.assertEqual(len(value['imported']),4)
        self.assertEqual(len(value['scenario']['away_tactic_pool']['entries']),4)
        self.assertEqual(value['roster_failures'],[])
        for entry in value['scenario']['away_tactic_pool']['entries']:
            self.assertEqual(entry['roster']['roster_size'],23)
            self.assertEqual([player['source_uid']for player in entry['roster']['players']],
                list(range(600,623)))
        self.assertEqual([row['venue']for row in value['imported']],['A','H','A','H'])
        self.assertTrue(all(('主场战术'in row['label'])or('客场战术'in row['label'])for row in value['imported']))

    def test_validation_rejects_own_team_foreign_league_and_concurrency(self):
        with self.assertRaises(ValueError):self.lib.generate_real_team(self.key,'17:200:2026',1)
        with self.assertRaises(ValueError):self.lib.generate_real_team(self.key,'18:300:2026',2)
        self.assertTrue(self.lib.real_generation_lock.acquire(blocking=False))
        try:
            with self.assertRaises(ValueError)as caught:
                self.lib.generate_real_team(self.key,'17:200:2026',2)
            self.assertIn('正在生成',str(caught.exception))
        finally:
            self.lib.real_generation_lock.release()

    def test_league_library_shows_generated_variants(self):
        started=self.patches()
        for patch in started:patch.start();self.addCleanup(patch.stop)
        self.lib.start_real_generation(self.key,'17:200:2026');self.wait_complete()
        with mock.patch.object(desktop_coach_presets,'ensure',return_value={'teams':[self.coach_row(2),self.coach_row(3)],'failures':[]}):
            self.lib.build_league_report(self.key,'17:200:2026')
            value=self.lib.league_library(self.key,'17:200:2026')
        self.assertEqual(value['status'],'complete')
        self.assertIsNotNone(value['real'])
        self.assertEqual(value['real']['variant_count'],4)
        rows={row['club_uid']:row for row in value['teams']}
        self.assertTrue(rows[2]['real']);self.assertTrue(all(variant['source']=='real_ai'for variant in rows[2]['variants']))
        self.assertEqual([variant['label']for variant in rows[2]['variants']],['队2主场战术','队2客场战术'])

    def write_library(self,teams,failures=()):
        value=desktop_real_library.build(SOURCE['source_sha256'],'17:200:2026',1,list(teams),list(failures),
            0,self.lib.real_binding(self.key))
        return desktop_real_library.save(self.lib,self.key,value)

    def real_team_row(self,club_uid,club,venues=('A','H')):
        variants=[]
        for venue in venues:
            index=1 if venue=='A' else 2
            word='主场'if venue=='A'else'客场'
            variants.append({'index':index,'venue':venue,'label':f'{club}{word}战术',
                'name':f'{club}-教练-{word}战术','tactic_name':f'真实-{club}-{venue}',
                'plan':{'mentality':5,'team_bits':'00'*16,'lineup_source_uids':list(range(11))},
                'roster':list(range(club_uid*100,club_uid*100+23)),'club_uid':club_uid,'club':club,
                'coach':f'教练{club_uid}','plan_sha256':hashlib.sha256(f'plan-{club_uid}-{venue}'.encode()).hexdigest(),
                'payload_sha256':'a'*64,'config_sha256':'b'*64,'generated_at':'2026-11-10T00:00:00+08:00'})
        return {'club_uid':club_uid,'club':club,'coach':f'教练{club_uid}','variants':variants}

    def preset_rows(self):
        return {'teams':[self.coach_row(2),self.coach_row(3)],'failures':[]}

    def test_export_merges_generated_and_preset_teams(self):
        started=self.patches()
        for patch in started:patch.start();self.addCleanup(patch.stop)
        self.lib.generate_real_team(self.key,'17:200:2026',2)
        with mock.patch.object(desktop_coach_presets,'ensure',return_value=self.preset_rows()),\
             mock.patch.object(desktop_coach_presets,'preset_by_index_team',return_value=preset_team()),\
             mock.patch.object(desktop_real_generation,'team_from_plan',return_value={'name':'队2'}):
            result=self.lib.export_league_tactics(self.key,'17:200:2026',str(self.directory))
        self.assertEqual(result['source'],'mixed')
        self.assertEqual((result['real_count'],result['preset_count']),(2,2))
        self.assertEqual(result['profile'],desktop_save_export.MIXED_PROFILE)
        self.assertEqual(len(result['files']),4)
        self.assertEqual(sorted({entry['club_uid']for entry in result['files']}),[2,3])
        self.assertEqual(result['skipped'],[])
        notice=(Path(result['directory'])/'导出说明.txt').read_text(encoding='utf8')
        self.assertIn('真实AI战术 2 套',notice);self.assertIn('教练偏好预设 2 套',notice)
        self.assertIn('career.fm',notice);self.assertNotIn('C:/saves',notice)

    def test_export_and_pool_import_fall_back_when_library_is_empty(self):
        failures=[{'club_uid':2,'club':'乙队','venue':'A','error':'主教练档案超出范围'}]
        self.write_library([],failures)
        scenario={'teams':[{'name':'甲'},{'name':'乙'}]}
        self.app.validate_scenario=lambda value:value
        with mock.patch.object(desktop_coach_presets,'ensure',return_value=self.preset_rows()),\
             mock.patch.object(desktop_coach_presets,'preset_by_index_team',return_value=preset_team()):
            result=self.lib.export_league_tactics(self.key,'17:200:2026',str(self.directory))
            imported=self.lib.import_league_tactics_pool(self.key,'17:200:2026',scenario)
        self.assertEqual(result['source'],'coach_preset')
        self.assertEqual(len(result['files']),4)
        self.assertEqual(result['generation_failures'],failures)
        self.assertEqual(imported['source'],'coach_preset')
        self.assertEqual(len(imported['imported']),4)
        self.assertEqual(imported['skipped'],[])
        self.assertEqual(len(imported['generation_failures']),1)

    def test_partial_variant_keeps_preset_column(self):
        self.write_library([self.real_team_row(2,'乙队',('H',))])
        with mock.patch.object(desktop_coach_presets,'ensure',return_value=self.preset_rows()),\
             mock.patch.object(desktop_coach_presets,'preset_by_index_team',return_value=preset_team()),\
             mock.patch.object(desktop_real_generation,'ensure',return_value={'inputs':{},'staff':{}}),\
             mock.patch.object(desktop_real_generation,'team_from_plan',return_value={'name':'队2'}):
            result=self.lib.export_league_tactics(self.key,'17:200:2026',str(self.directory))
        self.assertEqual((result['real_count'],result['preset_count']),(1,3))
        self.assertEqual(sorted((entry['club_uid'],entry['index'])for entry in result['files']),
            [(2,1),(2,2),(3,1),(3,2)])
        with mock.patch.object(desktop_coach_presets,'ensure',return_value=self.preset_rows()):
            self.lib.build_league_report(self.key,'17:200:2026')
            view=self.lib.league_library(self.key,'17:200:2026')
        row=next(team for team in view['teams']if team['club_uid']==2)
        self.assertEqual([variant.get('source')for variant in row['variants']],[None,'real_ai'])

    def test_import_pool_merges_generated_and_preset_teams(self):
        started=self.patches()
        for patch in started:patch.start();self.addCleanup(patch.stop)
        self.lib.generate_real_team(self.key,'17:200:2026',2)
        scenario={'teams':[{'name':'甲'},{'name':'乙'}]}
        self.app.validate_scenario=lambda value:value
        with mock.patch.object(desktop_coach_presets,'ensure',return_value=self.preset_rows()),\
             mock.patch.object(desktop_coach_presets,'preset_by_index_team',return_value=preset_team()),\
             mock.patch.object(desktop_real_generation,'team_from_plan',return_value=preset_team(extra='3')):
            value=self.lib.import_league_tactics_pool(self.key,'17:200:2026',scenario)
        self.assertEqual(value['source'],'mixed')
        self.assertEqual((value['real_count'],value['preset_count']),(2,2))
        self.assertEqual(len(value['imported']),4)
        self.assertEqual(value['skipped'],[])
        self.assertEqual(sorted(row['source']for row in value['imported']),['coach_preset']*2+['real_ai']*2)

    def test_export_reports_omitted_variants(self):
        ensured={'teams':[self.coach_row(2)],'failures':[{'club_uid':3,'name':'丙队','error':'主教练缺失'}]}
        with mock.patch.object(desktop_coach_presets,'ensure',return_value=ensured),\
             mock.patch.object(desktop_coach_presets,'preset_by_index_team',return_value=preset_team()):
            result=self.lib.export_league_tactics(self.key,'17:200:2026',str(self.directory))
        self.assertEqual(result['source'],'coach_preset')
        self.assertEqual(len(result['files']),2)
        self.assertEqual(len(result['skipped']),2)
        self.assertEqual({row['club_uid']for row in result['skipped']},{3})
        self.assertEqual(len(result['failures']),1)

    def test_export_keeps_generated_rows_when_preset_read_fails(self):
        started=self.patches()
        for patch in started:patch.start();self.addCleanup(patch.stop)
        self.lib.generate_real_team(self.key,'17:200:2026',2)
        with mock.patch.object(desktop_coach_presets,'ensure',side_effect=ValueError('预设读取失败')),\
             mock.patch.object(desktop_real_generation,'team_from_plan',return_value={'name':'队2'}):
            result=self.lib.export_league_tactics(self.key,'17:200:2026',str(self.directory))
        self.assertEqual(result['source'],'real_ai')
        self.assertEqual((result['real_count'],result['preset_count']),(2,0))
        self.assertEqual({row['club_uid']for row in result['skipped']},{3})
        self.assertTrue(any('教练偏好预设'in(item.get('club')or'')for item in result['failures']))

    def test_resolved_generation_failures_are_dropped(self):
        binding=self.lib.real_binding(self.key)
        existing=desktop_real_library.build(SOURCE['source_sha256'],'17:200:2026',1,
            [self.real_team_row(2,'乙队',('A',))],[{'club_uid':2,'venue':'H','error':'失败'}],0,binding)
        merged=desktop_real_library.merge(existing,'17:200:2026',1,SOURCE['source_sha256'],
            [self.real_team_row(2,'乙队',('A','H'))],[],1,binding)
        self.assertEqual(merged['failures'],[])
        self.assertEqual(len(desktop_real_library.variants(desktop_real_library.team(merged,2))),2)

    def test_export_loads_generation_inputs_once(self):
        started=self.patches()
        for patch in started:patch.start();self.addCleanup(patch.stop)
        self.lib.generate_real_team(self.key,'17:200:2026',2)
        with mock.patch.object(desktop_coach_presets,'ensure',return_value=self.preset_rows()),\
             mock.patch.object(desktop_coach_presets,'preset_by_index_team',return_value=preset_team()),\
             mock.patch.object(desktop_real_generation,'ensure',return_value={'inputs':{},'staff':{}})as ensure_mock,\
             mock.patch.object(desktop_real_generation,'team_from_plan',return_value={'name':'队2'}):
            self.lib.export_league_tactics(self.key,'17:200:2026',str(self.directory))
        self.assertEqual(ensure_mock.call_count,1)

    def test_engine_identity_change_invalidates_and_regenerates_library(self):
        started=self.patches()
        for patch in started:patch.start();self.addCleanup(patch.stop)
        self.lib.start_real_generation(self.key,'17:200:2026');self.wait_complete()
        self.assertIsNotNone(desktop_real_library.load(self.lib,self.key,'17:200:2026'))
        self.app.desktop_engine=_AlternateEngine();self.app.ENGINE_COMPATIBILITY={'resource_fingerprint':'changed'}
        self.lib.check_binding(self.lib.folder(self.key))
        self.assertIsNone(desktop_real_library.load(self.lib,self.key,'17:200:2026'))
        self.assertIsNone(self.lib.real_library(self.key,'17:200:2026'))
        self.assertEqual(self.lib.real_generation_status(self.key,'17:200:2026')['status'],'idle')
        state=self.lib.start_real_generation(self.key,'17:200:2026')
        self.assertEqual(state['status'],'reading')
        self.assertEqual(self.wait_complete()['status'],'complete')
        self.assertEqual(len(self.preview_calls),8)
        library=desktop_real_library.load(self.lib,self.key,'17:200:2026')
        self.assertEqual(library['binding'],self.lib.real_binding(self.key))

    def test_completion_state_is_published_after_generation_lock_release(self):
        started=self.patches()
        for patch in started:patch.start();self.addCleanup(patch.stop)
        observed=[];original=self.lib.write
        def write(path,value):
            if path.name.startswith('real_progress_')and isinstance(value,dict)and value.get('status')=='complete':
                observed.append(self.lib.real_generation_lock.locked())
            return original(path,value)
        with mock.patch.object(self.lib,'write',side_effect=write):
            self.lib.start_real_generation(self.key,'17:200:2026');self.wait_complete()
            deadline=time.time()+5
            while time.time()<deadline and not observed:time.sleep(0.01)
        self.assertTrue(observed);self.assertFalse(any(observed))
        again=self.lib.start_real_generation(self.key,'17:200:2026',force=True)
        self.assertEqual(again['status'],'reading')
        self.wait_complete()
        self.assertEqual(len(self.preview_calls),8)

    def test_status_reports_reading_while_single_team_generation_runs(self):
        gate=threading.Event();entered=threading.Event()
        def preview(lib,key,own,opponent,venue='H',seed=0,prepared=None):
            self.preview_calls.append((opponent,venue));entered.set();gate.wait(10);return self.result(opponent,venue)
        patches=[mock.patch.object(desktop_real_generation,'ensure',return_value={'inputs':{},'staff':{}}),
            mock.patch.object(desktop_real_generation,'preview',side_effect=preview)]
        for patch in patches:patch.start();self.addCleanup(patch.stop)
        results=[]
        worker=threading.Thread(target=lambda:results.append(self.lib.generate_real_team(self.key,'17:200:2026',2)))
        worker.start();self.assertTrue(entered.wait(10))
        self.assertEqual(self.lib.real_generation_status(self.key,'17:200:2026')['status'],'reading')
        gate.set();worker.join(10)
        self.assertEqual(results[0]['status'],'complete')

    def coach_row(self,club_uid):
        return {'club_uid':club_uid,'name':f'队{club_uid}','coach_name':f'教练{club_uid}','available':True,
            'variants':[{'index':1,'preset_index':1,'preset_sha256':'d'*64,'preset_name':'预设1','formation':'','formation_code':1,'exact':True,'position_difference':0},
                        {'index':2,'preset_index':2,'preset_sha256':'e'*64,'preset_name':'预设2','formation':'','formation_code':2,'exact':True,'position_difference':0}],'error':None}

class RealGenerationCacheTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root=ROOT/'build/test-temp';cls.temp_root.mkdir(parents=True,exist_ok=True)

    def setUp(self):
        self.holder=tempfile.TemporaryDirectory(dir=self.temp_root);self.root=Path(self.holder.name)
        self.app=_App(self.root);self.lib=desktop_save_mode.SaveLibrary(self.app)
        self.key='0123456789abcdef';self.folder=self.lib.root/self.key;self.folder.mkdir(parents=True)
        self.source=self.root/'career.fm';self.source.write_bytes(b'career-save')
        self.digest=hashlib.sha256(b'career-save').hexdigest()
        data={'schema':5,'source':str(self.source),'source_sha256':self.digest,'date':SOURCE['date'],
              'build':SOURCE['build'],'tactics':[],'fixtures':[],'selections':[],'caches':[],
              'managed':[{'club_uid':1}],'clubs':[],
              'leagues':[{'key':'17:200:2026','competition_id':17,'stage_id':200,'season':2026,
                          'club_uids':[1],'fixture_count':0,'first_date':'2026-08-01','last_date':'2027-05-01'}],
              'league_clubs':{}}
        (self.folder/'dataset.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf8')
        self.lib.check_binding(self.folder);desktop_save_mode.dataset.cache_clear()
        self.runs=[];self.native_calls=[]
        def fake_run(script,args,log_path,timeout):
            name=Path(script).name;self.runs.append(name);out=Path(args[1])
            if name=='desktop_generation_inputs.py':
                (out/'generation_inputs.json').write_text(json.dumps({'source_sha256':self.digest}),encoding='utf8')
            else:
                (out/'staff_fragments.json').write_text(json.dumps({'source_sha256':self.digest,
                    'human_ready':True,'rows':[]}),encoding='utf8')
            return types.SimpleNamespace(returncode=0)
        self.run_patch=mock.patch.object(desktop_real_generation,'_run',side_effect=fake_run);self.run_patch.start()
        self.addCleanup(self.run_patch.stop)
        self.native_patch=mock.patch.object(self.lib,'native',side_effect=lambda *args,**kwargs:[]);self.native_patch.start()
        self.addCleanup(self.native_patch.stop)

    def tearDown(self):
        desktop_save_mode.dataset.cache_clear();self.holder.cleanup()

    def test_staff_cache_is_bound_to_engine_identity(self):
        first=desktop_real_generation.ensure(self.lib,self.key)
        self.assertEqual(self.runs,['desktop_generation_inputs.py','desktop_real_generation_prepare.py'])
        self.assertEqual(first['binding'],self.lib.real_binding(self.key))
        desktop_real_generation.ensure(self.lib,self.key)
        self.assertEqual(len(self.runs),2)
        self.app.desktop_engine=_AlternateEngine();self.app.ENGINE_COMPATIBILITY={'resource_fingerprint':'changed'}
        self.lib.check_binding(self.folder)
        third=desktop_real_generation.ensure(self.lib,self.key)
        self.assertEqual(len(self.runs),4)
        self.assertNotEqual(third['binding'],first['binding'])

    def test_plan_cache_key_includes_engine_identity(self):
        identity=self.lib.real_binding(self.key)
        changed={'engine':{'host_sha256':'f'*64,'resource_fingerprint':'changed'},'fixture_sha256':None,
            'protocol':desktop_generation_protocol.PROFILE,'prep_version':desktop_real_generation.PREP_VERSION}
        first=desktop_real_generation.plan_cache(self.lib,self.key,'a'*32,0,identity)
        second=desktop_real_generation.plan_cache(self.lib,self.key,'a'*32,0,changed)
        self.assertNotEqual(first,second)

class RealGenerationPayloadTests(unittest.TestCase):
    def inputs(self):
        personality={'professionalism':15,'loyalty':12,'sportsmanship':10,'temperament':8,'pressure':14,'ambition':16,'adaptability':11}
        clubs=[{'uid':1,'unique_id':11,'reputation':7000,'nation_id':5,'teams':[{'team_id':101,'slot':0}]},
               {'uid':2,'unique_id':22,'reputation':6000,'nation_id':5,'teams':[{'team_id':102,'slot':0}]}]
        staff=[{'uid':7,'unique_id':17,'is_human_manager':True,'name':'甲帅','club_uid':1,'team_id':101,'team_slot':0,
                'job':{'raw':16},'has_contract':True,'person_selector':71,'personality':personality,'age':45},
               {'uid':8,'unique_id':18,'is_human_manager':False,'name':'乙帅','club_uid':2,'team_id':102,'team_slot':0,
                'job':{'raw':16},'has_contract':True,'person_selector':82,'personality':personality,'age':50}]
        players=[]
        for club in (1,2):
            for index in range(25):
                positions={'gk':18 if index==24 else 3,'dc':12,'mc':12}
                players.append({'uid':club*1000+index,'unique_id':club*100000+index,'name':f'{club}-{index}',
                    'club_uid':club,'ability':{'current':100-index},'positions':positions})
        return {'source_sha256':'e'*64,'clubs':clubs,'staff':staff,'players':players,'nations':{'5':105}}
    def native(self):
        return {'profile_hex':'11'*52,'native_d4_to_f4_hex':'00'*33,
                'generation_trait_pairs':[[1,2],[3,4]]}
    def test_manager_and_roster_selection(self):
        inputs=self.inputs()
        self.assertEqual(desktop_real_generation.manager(inputs,1,True)['name'],'甲帅')
        self.assertIsNone(desktop_real_generation.manager(inputs,1,False))
        self.assertEqual(desktop_real_generation.manager(inputs,2,False)['name'],'乙帅')
        chosen=desktop_real_generation.roster(inputs,1)
        self.assertEqual(len(chosen),23)
        self.assertTrue(any(desktop_real_generation.is_goalkeeper(player)for player in chosen))
        self.assertIn(100024,{player['unique_id']for player in chosen})
    def test_side_record_rejects_out_of_range_formation_codes(self):
        inputs=self.inputs();club=inputs['clubs'][1];coach=inputs['staff'][1]
        native=self.native();extra=bytearray(bytes.fromhex(native['native_d4_to_f4_hex']));extra[11]=65
        native['native_d4_to_f4_hex']=extra.hex()
        with self.assertRaises(ValueError)as caught:
            desktop_real_generation._side_record(inputs,club,coach,native,False,desktop_real_generation.roster(inputs,2))
        self.assertIn('主教练档案',str(caught.exception))

    def test_side_record_matches_native_duel_layout(self):
        inputs=self.inputs();club=inputs['clubs'][1];coach=inputs['staff'][1]
        players=desktop_real_generation.roster(inputs,2)
        record=desktop_real_generation._side_record(inputs,club,coach,self.native(),False,players)
        self.assertEqual(len(record),288)
        self.assertEqual(struct.unpack_from('<4I',record,0),
            (22,18,6000,len(players)))
        self.assertEqual(struct.unpack_from('<4I',record,272),(0,105,0xffffffff,0xffffffff))
        payload=struct.pack('<8s',b'FM27DUL1')+desktop_real_generation._side_record(
            inputs,inputs['clubs'][0],inputs['staff'][0],self.native(),True,desktop_real_generation.roster(inputs,1))+bytes(record)
        teams=[{'roster_size':23,'players':[{'source_uid':player['unique_id']}for player in desktop_real_generation.roster(inputs,1)]},
               {'roster_size':23,'players':[{'source_uid':player['unique_id']}for player in desktop_real_generation.roster(inputs,2)]}]
        normalized=desktop_generation_protocol.normalize({'profile':desktop_generation_protocol.PROFILE,'payload_hex':payload.hex()},teams)
        self.assertEqual(normalized['payload_hex'],payload.hex())

class ReusableSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_root=ROOT/'build/test-temp';cls.temp_root.mkdir(parents=True,exist_ok=True)

    def setUp(self):
        self.holder=tempfile.TemporaryDirectory(dir=self.temp_root);self.root=Path(self.holder.name)
        self.app=_App(self.root);self.lib=desktop_save_mode.SaveLibrary(self.app)

    def tearDown(self):
        desktop_save_mode.dataset.cache_clear();self.holder.cleanup()

    def test_requires_current_schema(self):
        digest='b'*64;folder=self.lib.root/'fedcba9876543210';folder.mkdir(parents=True)
        data={'source':SOURCE['source'],'source_sha256':digest,'reader_compatibility_profile':desktop_save_compat.PROFILE,
              'first_team_counts':{},'caches':[],'tactics':[],'clubs':[],'schema':3}
        self.lib.write(folder/'progress.json',{'status':'complete'})
        self.lib.write(folder/'dataset.json',data)
        self.assertIsNone(self.lib.reusable_source(digest))
        data['schema']=4;self.lib.write(folder/'dataset.json',data);desktop_save_mode.dataset.cache_clear()
        self.assertIsNone(self.lib.reusable_source(digest))
        data['schema']=5
        self.lib.write(folder/'dataset.json',data)
        (folder/'player_index.json').write_text('{}',encoding='utf8');(folder/'rosters').mkdir()
        desktop_save_mode.dataset.cache_clear()
        self.assertEqual(self.lib.reusable_source(digest),folder)

if __name__=='__main__':
    unittest.main()
