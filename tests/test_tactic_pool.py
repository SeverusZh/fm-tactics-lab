import copy
import json
import sys
import unittest
from unittest import mock
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import fm27_tactic_pool as pools


def cell(position='GK',role='Goalkeeper',duty='0'):
    return {'position':position,'role':role,'duty':duty,'instructions':{'1':0},'target_player':255,'target_position':0}


TACTIC_POSITIONS=['GK','DR','DCR','DCL','DL','DMC','MCR','MCL','AMR','AML','ST']


def tactic(name='测试战术',mentality=3,extra='0',plan=True):
    value={'tactic_name':name,'mentality':mentality,'instructions':{'1':2,'2':1},
        'native_extra_team_bits':extra,
        'phases':[[cell(position)for position in TACTIC_POSITIONS]for _ in range(2)]}
    if plan:value['native_source_plan']={'value':{'phases':[],'instructions':{}},'signature':'a'*64}
    return value


def team(name='球队'):
    return {'name':name,'tactic_name':'原战术','mentality':5,'instructions':{'1':1},
        'native_extra_team_bits':'4','phases':[[cell()for _ in range(11)],[cell()for _ in range(11)]],
        'lineup':list(range(11)),
        'players':[{'name':f'球员{index}','native_id':index,'attributes':[10]*69}for index in range(16)],
        'squad':[{'source_uid':index,'attributes':[7]*69}for index in range(2)],
        'native_source_plan':{'value':{'phases':[],'instructions':{}},'signature':'b'*64}}


def expected_positions(positions,slot):
    attrs=[10]*15;attrs[pools.POSITION_ATTRIBUTE_INDEX['GK']]=1
    attrs[pools.POSITION_ATTRIBUTE_INDEX[positions[slot]]]=pools.POSITION_FAMILIARITY
    return attrs


def roster(count=12,lineup=None):
    players=[{'name':f'存档球员{index+1}','source_uid':100+index,
        'attributes':[5]*15+[60]*54,'native_profile':{}}for index in range(count)]
    return {'club_uid':7,'club':'存档队','coach':'存档教练','source':'coach_preset',
        'roster_size':count,'lineup':list(range(11))if lineup is None else lineup,'players':players}


def entry(name='战术一',weight=1,plan=True,roster_value=None):
    value={'name':name,'weight':weight,'tactic':tactic(name,plan=plan)}
    if roster_value is not None:value['roster']=roster_value
    return value


def pool(entries=None,enabled=True,uniform=None,rotation=None,real=None):
    entries=[entry()]if entries is None else entries
    value={'profile':pools.PROFILE,'enabled':enabled,'entries':entries,
        'uniform':uniform or {'enabled':True,'attribute_value':15}}
    if rotation is not None:value['rotation']=rotation
    if real is not None:value['real']=real
    return value


def scenario(entries=None,enabled=True,uniform=None,rotation=None,real=None):
    return {'schema':3,'rules':'lab','fixture':'bundled_match_pkm',
        'teams':[team('主队'),team('客队')],
        'away_tactic_pool':pool(entries,enabled,uniform,rotation,real)}


class DefaultsTests(unittest.TestCase):
    def test_defaults_are_disabled_with_uniform_attributes(self):
        value=pools.defaults()
        self.assertEqual(value,{'enabled':False,'entries':[],
            'uniform':{'enabled':True,'attribute_value':pools.DEFAULT_ATTRIBUTE_VALUE},
            'rotation':{'enabled':False,'rounds':1},'real':{'enabled':False}})
        self.assertEqual(pools.DEFAULT_ATTRIBUTE_VALUE,15)
        self.assertEqual(pools.MAX_ENTRIES,128)
        self.assertEqual(pools.MAX_NAME,80)
        self.assertEqual(pools.PROFILE,'away-tactic-pool-v1')

    def test_normalize_fills_profile_for_legacy_absent_field(self):
        normalized=pools.normalize(pools.defaults())
        self.assertEqual(normalized,{'profile':pools.PROFILE,'enabled':False,'entries':[],
            'uniform':{'enabled':True,'attribute_value':15},
            'rotation':{'enabled':False,'rounds':1},'real':{'enabled':False}})
        legacy=pools.normalize({'profile':pools.PROFILE,'enabled':False,'entries':[],
            'uniform':{'enabled':True,'attribute_value':15}})
        self.assertEqual(legacy,normalized)


class NormalizeTests(unittest.TestCase):
    def test_rejects_invalid_top_level_values(self):
        for value in [None,[],{'enabled':True},{'profile':'other'},{'enabled':True,'entries':[]}]:
            with self.assertRaises(ValueError):
                pools.normalize(value)

    def test_rejects_too_many_entries(self):
        many=[entry(f'战术{index}')for index in range(pools.MAX_ENTRIES+1)]
        with self.assertRaisesRegex(ValueError,'最多允许'):
            pools.normalize({'entries':many})

    def test_accepts_entries_up_to_limit(self):
        many=[entry(f'战术{index}')for index in range(pools.MAX_ENTRIES)]
        self.assertEqual(len(pools.normalize({'entries':many})['entries']),pools.MAX_ENTRIES)

    def test_rejects_invalid_entry_fields(self):
        cases=[{'entries':'x'},{'entries':[{}]},{'entries':[{'name':'','weight':1,'tactic':tactic()}]},
            {'entries':[{'name':'a'*81,'weight':1,'tactic':tactic()}]},
            {'entries':[{'name':'a\nb','weight':1,'tactic':tactic()}]},
            {'entries':[{'name':'a','weight':0,'tactic':tactic()}]},
            {'entries':[{'name':'a','weight':1001,'tactic':tactic()}]},
            {'entries':[{'name':'a','weight':True,'tactic':tactic()}]},
            {'entries':[{'name':'a','weight':1.5,'tactic':tactic()}]},
            {'entries':[{'name':'a','weight':1,'tactic':tactic(),'extra':1}]},
            {'entries':[{'name':'a','weight':1,'tactic':None}]}]
        for value in cases:
            with self.assertRaises(ValueError):
                pools.normalize(value)

    def test_rejects_invalid_tactic_core(self):
        for mentality in [0,8,None,'3',True]:
            with self.assertRaises(ValueError):
                pools.normalize({'entries':[{'name':'a','weight':1,'tactic':{**tactic(),'mentality':mentality}}]})
        for instructions in [None,{'a':1},{'1':-1},{'1':1<<32},{'1':True},{'1':'2'}]:
            with self.assertRaises(ValueError):
                pools.normalize({'entries':[{'name':'a','weight':1,'tactic':{**tactic(),'instructions':instructions}}]})
        for extra in [None,1,'-1','12x','0'*40,str(1<<128)]:
            with self.assertRaises(ValueError):
                pools.normalize({'entries':[{'name':'a','weight':1,'tactic':{**tactic(),'native_extra_team_bits':extra}}]})

    def test_rejects_invalid_phases_and_cells(self):
        broken=[{**tactic(),'phases':[[]]},
            {**tactic(),'phases':[[cell()for _ in range(11)],[cell()for _ in range(10)]]},
            {**tactic(),'phases':[[cell()for _ in range(11)]+[None],[cell()for _ in range(11)]]}]
        for value in broken:
            with self.assertRaises(ValueError):
                pools.normalize({'entries':[{'name':'a','weight':1,'tactic':value}]})
        base=cell()
        for index,field in enumerate(['position','role','duty']):
            broken=dict(base);broken[field]=None
            with self.assertRaises(ValueError):
                pools.normalize({'entries':[{'name':'a','weight':1,'tactic':{**tactic(),'phases':[[broken]+[cell()for _ in range(10)],[cell()for _ in range(11)]]}}]})
        broken=dict(base);broken['target_player']=256
        with self.assertRaises(ValueError):
            pools.normalize({'entries':[{'name':'a','weight':1,'tactic':{**tactic(),'phases':[[broken]+[cell()for _ in range(10)],[cell()for _ in range(11)]]}}]})

    def test_rejects_invalid_source_plan_and_uniform(self):
        for plan in [{'value':{}},{'value':{},'signature':'x'},{'value':{},'signature':'a'*63},[],'x']:
            value={**tactic(),'native_source_plan':plan}
            with self.assertRaises(ValueError):
                pools.normalize({'entries':[{'name':'a','weight':1,'tactic':value}]})
        for uniform in [None, {'enabled':1,'attribute_value':15},{'enabled':True,'attribute_value':0},
                {'enabled':True,'attribute_value':21},{'enabled':True,'attribute_value':15.0}]:
            with self.assertRaises(ValueError):
                pools.normalize({'enabled':False,'entries':[entry()],'uniform':uniform})

    def test_canonicalizes_and_copies_input(self):
        source={'enabled':False,'entries':[{'name':'  战术一  ','weight':2,
            'tactic':{**tactic(extra='0004'),'instructions':{'01':0,'10':3}}}],
            'uniform':{'enabled':False,'attribute_value':7}}
        normalized=pools.normalize(source)
        self.assertEqual(normalized['entries'][0]['name'],'战术一')
        self.assertEqual(normalized['entries'][0]['tactic']['native_extra_team_bits'],'4')
        self.assertEqual(normalized['entries'][0]['tactic']['instructions'],{'1':0,'10':3})
        self.assertEqual(normalized['uniform'],{'enabled':False,'attribute_value':7})
        normalized['entries'][0]['tactic']['phases'][0][0]['position']='XX'
        self.assertEqual(source['entries'][0]['tactic']['phases'][0][0]['position'],'GK')


class ProbabilityTests(unittest.TestCase):
    def test_probabilities_follow_weights(self):
        entries=[entry('甲',1),entry('乙',3)]
        rows=pools.probabilities(entries)
        self.assertEqual([row['weight']for row in rows],[1,3])
        self.assertAlmostEqual(rows[0]['probability'],0.25)
        self.assertAlmostEqual(rows[1]['probability'],0.75)
        self.assertAlmostEqual(sum(row['probability']for row in rows),1.0)

    def test_single_entry_and_empty_pool(self):
        self.assertEqual(pools.probabilities([entry()]),[{'weight':1,'probability':1.0}])
        with self.assertRaises(ValueError):
            pools.probabilities([])

    def test_rejects_invalid_weight(self):
        with self.assertRaises(ValueError):
            pools.probabilities([{'weight':0}])


class DrawTests(unittest.TestCase):
    def test_draw_is_deterministic_for_same_salt_and_seed(self):
        entries=[entry('甲',1),entry('乙',2),entry('丙',3)]
        self.assertEqual(pools.draw_index(entries,41,'job-a'),pools.draw_index(copy.deepcopy(entries),41,'job-a'))
        self.assertEqual(pools.draw_index(entries,41,'job-a'),pools.draw_index(entries,41,'job-a'))

    def test_single_entry_always_drawn(self):
        entries=[entry('唯一',9)]
        self.assertEqual({pools.draw_index(entries,seed,'salt')for seed in range(50)},{0})

    def test_weighted_draw_matches_probabilities(self):
        entries=[entry('甲',1),entry('乙',4)]
        counts=[0,0]
        for seed in range(3000):counts[pools.draw_index(entries,seed,'dist')]+=1
        self.assertAlmostEqual(counts[0]/3000,0.2,delta=0.03)
        self.assertEqual(sum(counts),3000)

    def test_seed_and_salt_select_entries(self):
        entries=[entry('甲',1),entry('乙',1)]
        self.assertGreater(len({pools.draw_index(entries,seed,'x')for seed in range(30)}),1)
        self.assertGreater(len({pools.draw_index(entries,0,f'salt-{salt}')for salt in range(20)}),1)

    def test_draws_are_reproducible_and_bounded(self):
        value=pool([entry('甲',1),entry('乙',2),entry('丙',3)])
        seeds=[0,7,42,1000]
        first=pools.draws(value,seeds,'job-2')
        self.assertEqual(first,pools.draws(value,seeds,'job-2'))
        self.assertEqual(set(first),set(seeds))
        for seed,index in first.items():
            self.assertEqual(index,pools.draw_index(value['entries'],seed,'job-2'))
            self.assertTrue(0<=index<len(value['entries']))
        self.assertNotEqual(first[0],'0')
        with self.assertRaises(ValueError):
            pools.draws(value,[1.5],'job-2')


class CompletedDrawTests(unittest.TestCase):
    def test_same_seed_ab_pair_counts_as_one_draw(self):
        runs=[{'seed':42,'variant':variant,'tactic_pool_entry':{'index':1}}for variant in ('A','B')]
        runs.append({'seed':43,'variant':'B','tactic_pool_entry':{'index':0}})
        self.assertEqual(pools.completed_draw_counts(runs,2),{'0':1,'1':1})

    def test_conflicting_opponents_for_one_seed_are_rejected(self):
        runs=[{'seed':42,'tactic_pool_entry':{'index':index}}for index in (0,1)]
        with self.assertRaises(ValueError):pools.completed_draw_counts(runs,2)


class EntryTests(unittest.TestCase):
    def test_entry_from_imported_team(self):
        source=team('客队甲');source['tactic_name']='导入战术'
        value=pools.entry_from_team(source)
        self.assertEqual(value['name'],'导入战术')
        self.assertEqual(value['weight'],1)
        self.assertEqual(value['tactic']['tactic_name'],'导入战术')
        self.assertEqual(value['tactic']['mentality'],source['mentality'])
        self.assertEqual(value['tactic']['instructions'],source['instructions'])
        self.assertEqual(value['tactic']['native_extra_team_bits'],source['native_extra_team_bits'])
        self.assertEqual(value['tactic']['phases'],source['phases'])
        self.assertEqual(value['tactic']['native_source_plan'],source['native_source_plan'])
        value['tactic']['native_source_plan']['signature']='c'*64
        self.assertEqual(source['native_source_plan']['signature'],'b'*64)
        self.assertEqual(len(pools.normalize({'entries':[value]})['entries']),1)

    def test_entry_from_team_name_overrides_and_omits_source_plan(self):
        source=team('客队乙');source.pop('native_source_plan')
        value=pools.entry_from_team(source,'自定义名称')
        self.assertEqual(value['name'],'自定义名称')
        self.assertNotIn('native_source_plan',value['tactic'])

    def test_entry_from_team_rejects_invalid_name(self):
        with self.assertRaises(ValueError):
            pools.entry_from_team(team(),'')


class ApplyTests(unittest.TestCase):
    def test_apply_overrides_tactic_and_uniform_attributes(self):
        target=team('客队');before=copy.deepcopy(target)
        source=entry('统一战术')
        pools.apply(target,source,{'enabled':True,'attribute_value':15})
        self.assertEqual(target['tactic_name'],'统一战术')
        self.assertEqual(target['mentality'],3)
        self.assertEqual(target['instructions'],{'1':2,'2':1})
        self.assertEqual(target['native_extra_team_bits'],'0')
        self.assertEqual(target['phases'],source['tactic']['phases'])
        self.assertEqual(target['native_source_plan'],source['tactic']['native_source_plan'])
        for slot,player in enumerate(target['players'][:11]):
            self.assertEqual(player['attributes'][:15],expected_positions(TACTIC_POSITIONS,slot))
            self.assertEqual(player['attributes'][15:],[75]*54)
        for player in target['players'][11:]:
            self.assertEqual(player['attributes'][:15],[1]+[10]*14)
            self.assertEqual(player['attributes'][15:],[75]*54)
        self.assertEqual(target['squad'],before['squad'])

    def test_apply_removes_stale_source_plan_when_entry_has_none(self):
        target=team('客队')
        self.assertIn('native_source_plan',target)
        pools.apply(target,entry('无来源',plan=False),None)
        self.assertNotIn('native_source_plan',target)

    def test_apply_respects_disabled_uniform_and_custom_values(self):
        target=team('客队');original=copy.deepcopy(target['players'])
        pools.apply(target,entry('保留'),{'enabled':False,'attribute_value':20})
        self.assertEqual(target['players'],original)
        pools.apply(target,entry('统一'),{'enabled':True,'attribute_value':1})
        self.assertEqual(target['players'][0]['attributes'][:15],expected_positions(TACTIC_POSITIONS,0))
        self.assertEqual(target['players'][0]['attributes'][15:],[5]*54)
        pools.apply(target,entry('统一'),{'enabled':True,'attribute_value':20})
        self.assertEqual(target['players'][0]['attributes'][:15],expected_positions(TACTIC_POSITIONS,0))
        self.assertEqual(target['players'][0]['attributes'][15:],[100]*54)

    def test_apply_sets_natural_familiarity_for_assigned_positions(self):
        target=team('客队')
        positions=[['GK','DR','DCR','DCL','DL','DMC','MCR','MCL','AMR','AML','ST'],
                   ['GK','WBR','DC','DC','WBL','DMC','MC','MC','AMC','AMC','ST']]
        source=entry('位置')
        source['tactic']['phases']=[[cell(position)for position in positions[0]],[cell(position)for position in positions[1]]]
        pools.apply(target,source,{'enabled':True,'attribute_value':15})
        for slot in range(11):
            player=target['players'][target['lineup'][slot]]
            attributes=player['attributes']
            expected=[10]*15;expected[pools.POSITION_ATTRIBUTE_INDEX['GK']]=1
            for phase in range(2):
                expected[pools.POSITION_ATTRIBUTE_INDEX[positions[phase][slot]]]=pools.POSITION_FAMILIARITY
            self.assertEqual(attributes[:15],expected)
            self.assertEqual(attributes[15:],[75]*54)

    def test_apply_guarantees_familiarity_for_every_catalog_position(self):
        positions=list(pools.POSITION_ATTRIBUTE_INDEX)
        for start in range(0,len(positions),11):
            batch=(positions[start:start+11]+positions)[:11]
            target=team('客队')
            source=entry('位置')
            source['tactic']['phases']=[[cell(position)for position in batch]for _ in range(2)]
            pools.apply(target,source,{'enabled':True,'attribute_value':15})
            for slot in range(11):
                player=target['players'][target['lineup'][slot]]
                self.assertEqual(player['attributes'][:15],expected_positions(batch,slot))
                self.assertEqual(player['attributes'][15:],[75]*54)
        self.assertGreaterEqual(len(pools.POSITION_ATTRIBUTE_INDEX),24)

    def test_apply_rejects_unknown_tactic_position(self):
        target=team('客队')
        source=entry('未知位置')
        source['tactic']['phases'][0][0]['position']='XX'
        with self.assertRaises(ValueError)as caught:
            pools.apply(target,source,{'enabled':True,'attribute_value':15})
        self.assertIn('未知位置',str(caught.exception))

    def test_verify_detects_tampered_familiarity_or_attributes(self):
        target=team('客队')
        pools.apply(target,entry('统一'),{'enabled':True,'attribute_value':15})
        self.assertTrue(pools.verify(target,15))
        target['players'][0]['attributes'][pools.POSITION_ATTRIBUTE_INDEX['GK']]=1
        with self.assertRaises(ValueError):
            pools.verify(target,15)
        target=team('客队')
        pools.apply(target,entry('统一'),{'enabled':True,'attribute_value':15})
        target['players'][0]['attributes'][pools.POSITION_ATTRIBUTES]=70
        with self.assertRaises(ValueError):
            pools.verify(target,15)

    def test_apply_rejects_incomplete_player_attributes(self):
        target=team('客队');target['players'][0]['attributes']=[10]*68
        with self.assertRaises(ValueError):
            pools.apply(target,entry(),{'enabled':True,'attribute_value':15})


class ExpandTests(unittest.TestCase):
    def test_execution_policy_and_real_player_ca_survive_each_draw(self):
        source=scenario([entry('甲'),entry('乙')])
        source['experimental_execution']=[{'understanding':20,'buy_in':35,'opposition':80},
                                          {'understanding':85,'buy_in':65,'opposition':30}]
        for i,p in enumerate(source['teams'][1]['players']):
            p['native_profile']={'current_ability':90+i}
        before=copy.deepcopy(source)
        for index in range(2):
            expanded=pools.expand(source,index)
            self.assertEqual(expanded['experimental_execution'],source['experimental_execution'])
            self.assertEqual([p['native_profile']['current_ability']for p in expanded['teams'][1]['players']],
                             list(range(90,106)))
            expanded['experimental_execution'][1]['understanding']=0
        self.assertEqual(source,before)

    def test_expand_copies_scenario_and_removes_pool(self):
        source=scenario([entry('甲'),entry('乙')]);snapshot=copy.deepcopy(source)
        expanded=pools.expand(source,1)
        self.assertNotIn('away_tactic_pool',expanded)
        self.assertEqual(source,snapshot)
        self.assertEqual(expanded['teams'][1]['tactic_name'],'乙')
        self.assertEqual(expanded['teams'][1]['mentality'],3)
        self.assertEqual(expanded['teams'][0]['tactic_name'],'原战术')
        for slot,player in enumerate(expanded['teams'][1]['players'][:11]):
            self.assertEqual(player['attributes'][:15],expected_positions(TACTIC_POSITIONS,slot))
            self.assertEqual(player['attributes'][15:],[75]*54)
        for player in expanded['teams'][1]['players'][11:]:
            self.assertEqual(player['attributes'][:15],[1]+[10]*14)
            self.assertEqual(player['attributes'][15:],[75]*54)
        expanded['teams'][1]['phases'][0][0]['position']='XX'
        self.assertEqual(source['teams'][1]['phases'][0][0]['position'],'GK')

    def test_expand_side_and_invalid_requests(self):
        source=scenario([entry('甲'),entry('乙')])
        home=pools.expand(source,0,side=0)
        self.assertEqual(home['teams'][0]['tactic_name'],'甲')
        self.assertEqual(home['teams'][1]['tactic_name'],'原战术')
        for index in [2,-1,'0',None]:
            with self.assertRaises(ValueError):
                pools.expand(source,index)
        with self.assertRaises(ValueError):
            pools.expand({'schema':3,'teams':source['teams']},0)
        with self.assertRaises(ValueError):
            pools.expand(scenario([],enabled=False),0)

    def test_expand_fast_path_matches_normalized_pool(self):
        source=scenario([entry('甲',roster_value=roster()),entry('乙',roster_value=roster())],
            real={'enabled':True})
        normalized=pools.normalize(source['away_tactic_pool'])
        for index in range(2):
            self.assertEqual(pools.expand(source,index,pool_value=normalized),
                pools.expand(source,index))

    def test_expand_fast_path_skips_pool_normalization(self):
        source=scenario([entry('甲')])
        normalized=pools.normalize(source['away_tactic_pool'])
        with mock.patch.object(pools,'normalize',wraps=pools.normalize)as spy:
            pools.expand(source,0,pool_value=normalized)
            spy.assert_not_called()

    def test_expand_follows_saved_draws(self):
        value=pool([entry('甲',1),entry('乙',3),entry('丙',2)])
        source=scenario(value['entries'])
        seeds=[11,12,13,14]
        chosen=pools.draws(value,seeds,'job-3')
        for seed,index in chosen.items():
            expanded=pools.expand(source,index)
            self.assertEqual(expanded['teams'][1]['tactic_name'],value['entries'][index]['name'])
            self.assertEqual(expanded,pools.expand(source,index))


class ModeValidationTests(unittest.TestCase):
    def test_rejects_invalid_rotation_and_real_settings(self):
        for rotation in [None, [], {'enabled':1,'rounds':1},{'enabled':False,'rounds':0},
                {'enabled':False,'rounds':pools.MAX_ROUNDS+1},{'enabled':False,'rounds':True},
                {'enabled':False,'rounds':1,'extra':1}]:
            with self.assertRaises(ValueError):
                pools.normalize({'entries':[entry()],'rotation':rotation})
        for real in [None, [], {'enabled':'yes'}, {'enabled':False,'extra':1}]:
            with self.assertRaises(ValueError):
                pools.normalize({'entries':[entry()],'real':real})

    def test_real_mode_requires_roster_on_every_entry(self):
        with self.assertRaisesRegex(ValueError,'真实名单模式需要每套客队战术都带存档球员名单'):
            pools.normalize({'entries':[entry('有名单',roster_value=roster()),entry('缺名单')],
                'real':{'enabled':True}})
        value=pools.normalize({'entries':[entry('有名单',roster_value=roster())],
            'real':{'enabled':True}})
        self.assertTrue(value['real']['enabled'])
        self.assertEqual(value['entries'][0]['roster']['roster_size'],12)

    def test_rejects_invalid_entry_roster(self):
        base=roster()
        cases=[{**base,'players':base['players'][:10]},
            {**base,'roster_size':11},
            {**base,'lineup':[0]*11},
            {**base,'lineup':[0,1,2,3,4,5,6,7,8,9,12]},
            {**base,'source':'manual'},
            {**base,'players':[{**base['players'][0],'attributes':[5]*68}]+base['players'][1:]},
            {**base,'players':[{**base['players'][0],'attributes':[-1]+[60]*68}]+base['players'][1:]},
            {**base,'players':[base['players'][0],copy.deepcopy(base['players'][0])]+base['players'][2:]},
            {**base,'players':[{**base['players'][0],'source_uid':None}]+base['players'][1:]},
            {**base,'extra':1},
            {k:value for k,value in base.items()if k!='players'}]
        for value in cases:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    pools.normalize({'entries':[entry('名单',roster_value=value)]})

    def test_rotation_match_limit_is_validated_on_save(self):
        entries=[entry(f'战术{index}')for index in range(11)]
        with self.assertRaisesRegex(ValueError,'轮战每方案最多'):
            pools.normalize({'entries':entries,'rotation':{'enabled':True,'rounds':1000}})
        self.assertEqual(len(pools.normalize({'entries':entries[:10],
            'rotation':{'enabled':True,'rounds':1000}})['entries']),10)

    def test_roster_bytes_are_limited(self):
        original=pools.MAX_ROSTER_BYTES
        pools.MAX_ROSTER_BYTES=1000
        try:
            with self.assertRaisesRegex(ValueError,'超过'):
                pools.normalize({'entries':[entry('名单',roster_value=roster())]})
        finally:
            pools.MAX_ROSTER_BYTES=original
        pools.normalize({'entries':[entry('名单',roster_value=roster())]})

    def test_entry_roster_round_trips_and_is_copied(self):
        source=roster();source['players'][0]['name']='  存档前锋  '
        value=pools.normalize({'entries':[entry('名单',roster_value=source)]})
        saved=value['entries'][0]['roster']
        self.assertEqual(saved['players'][0]['name'],'存档前锋')
        saved['players'][0]['name']='改动'
        self.assertEqual(source['players'][0]['name'],'  存档前锋  ')


class RotationDrawTests(unittest.TestCase):
    def test_rotation_cycles_entries_round_by_round(self):
        value=pool([entry('甲'),entry('乙'),entry('丙')],
            rotation={'enabled':True,'rounds':2})
        seeds=[10,11,12,13,14,15]
        self.assertEqual(pools.draws(value,seeds,'salt'),
            {10:0,11:1,12:2,13:0,14:1,15:2})
        self.assertEqual(pools.rotation_matches(value),6)

    def test_rotation_rejects_seed_count_not_matching_rounds(self):
        value=pool([entry('甲'),entry('乙')],rotation={'enabled':True,'rounds':3})
        with self.assertRaisesRegex(ValueError,'2 套 × 3 轮 = 6 场'):
            pools.draws(value,[1,2,3,4,5],'salt')
        self.assertEqual(pools.draws(value,[1,2,3,4,5,6],'salt'),
            {1:0,2:1,3:0,4:1,5:0,6:1})

    def test_single_entry_rotation_repeats_candidate(self):
        value=pool([entry('唯一')],rotation={'enabled':True,'rounds':3})
        self.assertEqual(pools.draws(value,[7,8,9],'salt'),{7:0,8:0,9:0})

    def test_random_mode_ignores_rounds(self):
        value=pool([entry('甲'),entry('乙')],rotation={'enabled':False,'rounds':4})
        rows=pools.draws(value,[1,2,3],'salt')
        self.assertEqual(set(rows),{1,2,3})


class RealRosterTests(unittest.TestCase):
    def test_apply_overwrites_matchday_roster_and_keeps_native_ids(self):
        target=team('客队');native_ids=[player['native_id']for player in target['players']]
        source=entry('真实战术',roster_value=roster())
        pools.apply(target,source,real=True)
        self.assertEqual(target['roster_size'],12)
        self.assertEqual(target['lineup'],list(range(11)))
        self.assertNotIn('squad',target)
        self.assertEqual(target['captains'],[])
        for index in range(12):
            self.assertEqual(target['players'][index]['name'],f'存档球员{index+1}')
            self.assertEqual(target['players'][index]['source_uid'],100+index)
            self.assertEqual(target['players'][index]['attributes'],[5]*15+[60]*54)
            self.assertEqual(target['players'][index]['native_id'],native_ids[index])
        for player in target['players'][12:]:
            self.assertEqual(player['name'],'未入比赛名单')
            self.assertNotIn('source_uid',player)
        self.assertTrue(pools.verify_roster(target,source['roster']))

    def test_apply_real_mode_rejects_missing_or_tampered_roster(self):
        with self.assertRaisesRegex(ValueError,'真实名单模式缺少存档球员名单'):
            pools.apply(team('客队'),entry('无名单'),real=True)
        target=team('客队');source=entry('真实战术',roster_value=roster())
        pools.apply(target,source,real=True)
        target['players'][0]['attributes'][0]=1
        with self.assertRaises(ValueError):
            pools.verify_roster(target,source['roster'])

    def test_apply_real_mode_remaps_away_setpiece_and_leadership_choices(self):
        target=team('客队');source=entry('真实战术',roster_value=roster())
        for index in range(12):target['players'][index]['source_uid']=100+index
        target['players'][12]['source_uid']=999
        target['captains']=[1,12];target['takers']={'penalties':[2,12]}
        target['setpieces']={'role_priorities':{'penalties':[3,12]}}
        pools.apply(target,source,real=True)
        self.assertEqual(target['captains'],[1])
        self.assertEqual(target['takers'],{'penalties':[2]})
        self.assertEqual(target['setpieces']['role_priorities'],{'penalties':[3]})

    def test_apply_real_mode_deduplicates_remapped_duplicate_source_uids(self):
        target=team('客队');source=entry('真实战术',roster_value=roster())
        target['players'][0]['source_uid']=100;target['players'][1]['source_uid']=100
        target['captains']=[0,1];target['takers']={'penalties':[0,1]}
        target['setpieces']={'role_priorities':{'penalties':[0,1]}}
        pools.apply(target,source,real=True)
        self.assertEqual(target['captains'],[0])
        self.assertEqual(target['takers'],{'penalties':[0]})
        self.assertEqual(target['setpieces']['role_priorities'],{'penalties':[0]})
        target=team('客队');target['captains']=[];target['takers']={'penalties':[]}
        target['setpieces']={'role_priorities':{'penalties':[]}}
        pools.apply(target,source,real=True)
        self.assertEqual(target['captains'],[])
        self.assertEqual(target['takers'],{'penalties':[]})
        self.assertEqual(target['setpieces']['role_priorities'],{'penalties':[]})

    def test_apply_real_mode_ignores_uniform_settings(self):
        target=team('客队')
        pools.apply(target,entry('真实战术',roster_value=roster()),
            {'enabled':True,'attribute_value':20},real=True)
        self.assertEqual(target['players'][0]['attributes'],[5]*15+[60]*54)

    def test_expand_real_mode_applies_saved_roster_only_to_away_side(self):
        source=scenario([entry('真实甲',roster_value=roster())],real={'enabled':True})
        expanded=pools.expand(source,0)
        self.assertNotIn('away_tactic_pool',expanded)
        away=expanded['teams'][1]
        self.assertEqual(away['tactic_name'],'真实甲')
        self.assertEqual(away['roster_size'],12)
        self.assertEqual([player['name']for player in away['players'][:11]],
            [f'存档球员{index+1}'for index in range(11)])
        self.assertEqual(expanded['teams'][0],source['teams'][0])

    def test_roster_from_team_extracts_current_matchday_squad(self):
        source=team('客队')
        for index,player in enumerate(source['players']):player['source_uid']=500+index
        source['roster_size']=13;source['lineup']=list(range(11))
        value=pools.roster_from_team(source,9,'乙队','乙帅','coach_preset')
        self.assertEqual(value['club_uid'],9)
        self.assertEqual(value['roster_size'],13)
        self.assertEqual([player['source_uid']for player in value['players']],list(range(500,513)))
        self.assertEqual(value['lineup'],list(range(11)))
        with self.assertRaises(ValueError):
            pools.roster_from_team({'players':[]},9,'乙队','乙帅','coach_preset')


class SummaryTests(unittest.TestCase):
    def test_summary_exposes_public_fields_and_probabilities(self):
        value=pool([entry('甲',1),entry('乙',3)])
        result=pools.summary(value,'job-4')
        self.assertEqual(result['profile'],pools.PROFILE)
        self.assertEqual(result['salt'],'job-4')
        self.assertEqual(result['uniform'],{'enabled':True,'attribute_value':15})
        self.assertEqual([row['index']for row in result['entries']],[0,1])
        self.assertEqual([row['name']for row in result['entries']],['甲','乙'])
        self.assertAlmostEqual(sum(row['probability']for row in result['entries']),1.0)
        self.assertEqual(set(result['entries'][0]),{'index','name','weight','probability','roster'})
        self.assertEqual(result['mode'],'random')
        self.assertEqual(result['rounds'],1)
        self.assertEqual(result['players'],'uniform')
        self.assertNotIn('native_extra_team_bits',json.dumps(result))

    def test_summary_without_salt_omits_it(self):
        self.assertNotIn('salt',pools.summary(pool()))

    def test_rotation_summary_has_no_draw_probability(self):
        value=pool([entry('甲'),entry('乙')],rotation={'enabled':True,'rounds':2})
        result=pools.summary(value)
        self.assertEqual(result['mode'],'rotation')
        self.assertEqual(result['rounds'],2)
        self.assertTrue(all(row['probability']is None for row in result['entries']))


if __name__=='__main__':
    unittest.main()
