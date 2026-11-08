import copy
import json
import sys
import unittest
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


def entry(name='战术一',weight=1,plan=True):
    return {'name':name,'weight':weight,'tactic':tactic(name,plan=plan)}


def pool(entries=None,enabled=True,uniform=None):
    entries=[entry()]if entries is None else entries
    return {'profile':pools.PROFILE,'enabled':enabled,'entries':entries,
        'uniform':uniform or {'enabled':True,'attribute_value':15}}


def scenario(entries=None,enabled=True,uniform=None):
    return {'schema':3,'rules':'lab','fixture':'bundled_match_pkm',
        'teams':[team('主队'),team('客队')],
        'away_tactic_pool':pool(entries,enabled,uniform)}


class DefaultsTests(unittest.TestCase):
    def test_defaults_are_disabled_with_uniform_attributes(self):
        value=pools.defaults()
        self.assertEqual(value,{'enabled':False,'entries':[],
            'uniform':{'enabled':True,'attribute_value':pools.DEFAULT_ATTRIBUTE_VALUE}})
        self.assertEqual(pools.DEFAULT_ATTRIBUTE_VALUE,15)
        self.assertEqual(pools.MAX_ENTRIES,64)
        self.assertEqual(pools.PROFILE,'away-tactic-pool-v1')

    def test_normalize_fills_profile_for_legacy_absent_field(self):
        normalized=pools.normalize(pools.defaults())
        self.assertEqual(normalized,{'profile':pools.PROFILE,'enabled':False,'entries':[],
            'uniform':{'enabled':True,'attribute_value':15}})


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
            {'entries':[{'name':'a'*61,'weight':1,'tactic':tactic()}]},
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

    def test_apply_rejects_incomplete_player_attributes(self):
        target=team('客队');target['players'][0]['attributes']=[10]*68
        with self.assertRaises(ValueError):
            pools.apply(target,entry(),{'enabled':True,'attribute_value':15})


class ExpandTests(unittest.TestCase):
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

    def test_expand_follows_saved_draws(self):
        value=pool([entry('甲',1),entry('乙',3),entry('丙',2)])
        source=scenario(value['entries'])
        seeds=[11,12,13,14]
        chosen=pools.draws(value,seeds,'job-3')
        for seed,index in chosen.items():
            expanded=pools.expand(source,index)
            self.assertEqual(expanded['teams'][1]['tactic_name'],value['entries'][index]['name'])
            self.assertEqual(expanded,pools.expand(source,index))


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
        self.assertEqual(set(result['entries'][0]),{'index','name','weight','probability'})
        self.assertNotIn('native_extra_team_bits',json.dumps(result))

    def test_summary_without_salt_omits_it(self):
        self.assertNotIn('salt',pools.summary(pool()))


if __name__=='__main__':
    unittest.main()
