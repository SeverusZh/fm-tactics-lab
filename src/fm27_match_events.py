"""Attribute original goal/card events and reconcile goals with score reversals."""
from collections import Counter


def _people(scenario):
    generated='native_generation'in scenario
    return [{p.get('source_uid',p['native_id'])if generated else p['native_id']:p for p in t['players']}for t in scenario['teams']]

def _merge_cards(cards):
    """A sending-off notification and a second booking can arrive either way."""
    result=[];seen=set();dismissals={}
    for card in cards:
        player=card['player'];identity=(player['side'],player['native_id'])
        key=(identity,card['card'],card['tick'])
        if key in seen:continue
        seen.add(key);previous=dismissals.get(identity)
        if previous is not None:
            old=result[previous]
            same_incident=abs(old['tick']-card['tick'])<=1
            if same_incident and card['card']=='red':continue
            if same_incident and card['card']=='second_yellow':
                result[previous]=card;continue
        if card['card']in ['red','second_yellow']:dismissals[identity]=len(result)
        result.append(card)
    return result


def _collect_queue(rows,scenario,position_names):
    marker=next((r for r in rows if r.get('event')=='native_player_match_totals'),None)
    if marker is None or not(marker.get('observer_installed')or marker.get('queue_observations')):return {'collected':False,'goals':[],'cancelled_goals':[],'cards':[]}
    people=_people(scenario)
    def person(raw):
        if not raw:return None
        value=dict(raw);value['name']=people[raw['side']].get(raw['native_id'],{}).get('name','球员 #'+str(raw['native_id']))
        for phase in ['ip','oop']:value[phase+'_position']=position_names.get(raw[phase+'_position'],'未知')
        return value
    used=set();pending=[];goals=[];cards=[];score=[0,0];seen_cards=set()
    for row in rows:
        event=row.get('event')
        if event=='native_goal_event':pending.append(row)
        elif event=='observed_score_change':
            for side in range(2):
                difference=row['score'][side]-score[side]
                if difference>0:
                    for _ in range(difference):
                        raw=next((r for r in reversed(pending)if r.get('scoring_side')==side and r['tick']<=row['tick']and id(r)not in used),None)
                        if raw:used.add(id(raw))
                        scorer=person(raw.get('scorer'))if raw else None;assist=person(raw.get('assist'))if raw else None
                        own_goal=bool(scorer and scorer['side']!=side)
                        valid_assist=assist if assist and assist['side']==side and not own_goal and (not scorer or assist['native_id']!=scorer['native_id'])else None
                        goals.append({'side':side,'tick':row['tick'],'clock':row.get('clock'),'scorer':scorer,'assist':valid_assist,'own_goal':own_goal,'cancelled':False})
                elif difference<0:
                    for _ in range(-difference):
                        previous=next((g for g in reversed(goals)if g['side']==side and not g['cancelled']),None)
                        if previous:previous['cancelled']=True
            score=row['score'][:]
        elif event=='native_card_event':
            player=person(row.get('player'))
            if not player:continue
            key=(player['side'],player['native_id'],row['native_packet_kind'],row['event_tick'])
            if key in seen_cards:continue
            seen_cards.add(key)
            cards.append({'tick':row['tick'],'clock':row['clock'],'card':row['card'],'player':player,'native_code':row['native_packet_kind']})
    cards=_merge_cards(cards)
    valid=[g for g in goals if not g['cancelled']];observed=Counter((g['scorer']['side'],g['scorer']['native_id'])for g in valid if g['scorer']and not g['own_goal'])
    expected={(p['side'],p['native_id']):p['goals']for p in marker['players']if p['goals']}
    verified=dict(observed)==expected and all(g['scorer']for g in valid)
    observed_cards=Counter()
    for c in cards:
        key=(c['player']['side'],c['player']['native_id']);observed_cards[key,'yellow']+=int(c['card']in ['yellow','second_yellow']);observed_cards[key,'red']+=int(c['card']in ['red','second_yellow'])
    expected_cards=Counter()
    for p in marker['players']:
        key=(p['side'],p['native_id']);expected_cards[key,'yellow']=p.get('yellow_cards',0);expected_cards[key,'red']=p.get('red_cards',0)
    cards_verified=observed_cards==expected_cards
    return {'collected':True,'source':'original_native_event_queue','goals':valid,'cancelled_goals':[g for g in goals if g['cancelled']],'cards':cards,'scorers_verified_against_native_totals':verified,'cards_verified_against_native_totals':cards_verified,'native_player_totals':[p for p in marker['players']if p['goals']or p.get('yellow_cards')or p.get('red_cards')]}


def _counts(events):
    goals=Counter((g['scorer']['side'],g['scorer']['native_id'])for g in events['goals']if g.get('scorer')and not g['own_goal'])
    cards=Counter()
    for c in events['cards']:
        key=(c['player']['side'],c['player']['native_id'])
        cards[key,'yellow']+=int(c['card']in ['yellow','second_yellow'])
        cards[key,'red']+=int(c['card']in ['red','second_yellow'])
    return goals,cards


def collect(rows,scenario,position_names):
    events=_collect_queue(rows,scenario,position_names)
    marker=next((r for r in rows if r.get('event')=='native_player_match_totals'),None)
    if marker is None:return events
    expected_goals=Counter({(p['side'],p['native_id']):p['goals']for p in marker['players']if p['goals']})
    expected_cards=Counter()
    for p in marker['players']:
        for kind,field in [('yellow','yellow_cards'),('red','red_cards')]:
            expected_cards[(p['side'],p['native_id']),kind]=p.get(field,0)
    finish=next((r for r in rows if r.get('event')=='natural_match_finished'),None)
    registry=next((r for r in reversed(rows)if r.get('event')=='native_final_incident_registry'),None)if finish else None
    registry_error=None;registry_verified=False
    if registry is not None:
        try:
            if registry.get('valid')is False:raise ValueError(registry.get('error','registry_read_failed'))
            people={(p['side'],p['roster_index']):p for p in marker['players']}
            names=[{uid:p.get('name',str(uid))for uid,p in people.items()}for people in _people(scenario)]
            def person(side,index,raw=None):
                p=people.get((side,index))
                if p is None:return None
                if raw and raw['native_id']!=p['native_id']:raise ValueError('registry_player_identity_mismatch')
                return {'side':side,'roster_index':index,'native_id':p['native_id'],
                        'ip_position':position_names.get(p.get('ip_position',0),'未知'),
                        'oop_position':position_names.get(p.get('oop_position',0),'未知'),
                        'name':names[side].get(p['native_id'],'球员 #'+str(p['native_id'])),
                        'position_source':'final_snapshot'}
            goals=[];cards=[]
            for item in registry['incidents']:
                kind=item['native_type']
                if kind not in [1,2,3,14,15,38]:continue
                actor=person(item['side'],item['roster_index'],item.get('person'))
                if actor is None:raise ValueError('registry_event_player_not_in_native_roster')
                minute=item['nominal_minute'];added=item['added_minute']
                common={'tick':item['native_tick'],'clock':None,'nominal_minute':minute,'added_minute':added,
                        'display_minute':str(minute)+('+'+str(added)if added else''),
                        'source':'original_final_incident_registry'}
                if kind in [1,2,3]:
                    own=kind==2;side=1-actor['side']if own else actor['side']
                    assist=person(item['other_side'],item['other_index'],item.get('other_person'))if not own and item['other_side']==side else None
                    goals.append({**common,'side':side,'scorer':actor,'assist':assist,'own_goal':own,'penalty_goal':kind==3,'cancelled':False})
                else:
                    cards.append({**common,'card':{14:'second_yellow',15:'red',38:'yellow'}[kind],
                                  'player':actor,'native_code':kind})
            final={'goals':goals,'cards':_merge_cards(cards)}
            observed_goals,observed_cards=_counts(final)
            if observed_goals!=expected_goals:raise ValueError('registry_goals_disagree_with_native_player_totals')
            if not all(g['scorer']for g in goals)or[sum(g['side']==side for g in goals)for side in range(2)]!=finish['score']:
                raise ValueError('registry_goals_disagree_with_native_score')
            if observed_cards!=expected_cards:raise ValueError('registry_cards_disagree_with_native_player_totals')
            registry_verified=True
            # Keep precise event-time positions and clock where the queue was
            # already complete. The final registry independently validates it.
            if not events.get('scorers_verified_against_native_totals'):
                events['provisional_queue_goals']=events['goals'];events['goals']=goals
                events['goal_source']='original_final_incident_registry'
            if not events.get('cards_verified_against_native_totals'):
                events['provisional_queue_cards']=events['cards'];events['cards']=final['cards']
                events['card_source']='original_final_incident_registry'
            events.update(collected=True,scorers_verified_against_native_totals=True,cards_verified_against_native_totals=True)
        except (ValueError,KeyError,TypeError,IndexError)as error:
            registry_error=str(error)
            events.update(scorers_verified_against_native_totals=False,cards_verified_against_native_totals=False)
    observed_goals,observed_cards=_counts(events)
    def differences(expected,observed):
        return [{'identity':list(key),'expected':expected[key],'observed':observed[key]}
                for key in sorted(set(expected)|set(observed))if expected[key]!=observed[key]]
    events['integrity']={'registry_present':registry is not None,'registry_verified':registry_verified,
                         'registry_error':registry_error,
                         'goal_differences':differences(expected_goals,observed_goals),
                         'card_differences':differences(expected_cards,observed_cards),
                         'queue_observations':marker.get('queue_observations'),
                         'nonzero_packet_padding_observations':marker.get('nonzero_packet_padding_observations')}
    return events

def distribution(runs):
    people={};positions={};available=0;unverified_goals=0;unverified_cards=0
    for run in runs:
        events=run.get('events')or{}
        if not events.get('collected'):continue
        available+=1
        unverified_goals+=int(events.get('scorers_verified_against_native_totals')is False);unverified_cards+=int(events.get('cards_verified_against_native_totals')is False)
        def credit(player,metric):
            if not player:return
            key=(player['side'],player['native_id']);item=people.setdefault(key,{'side':key[0],'native_id':key[1],'name':player['name'],'goals':0,'assists':0,'own_goals':0,'yellow_cards':0,'red_cards':0});item[metric]+=1
            key=(player['side'],player['ip_position'],player['oop_position']);item=positions.setdefault(key,{'side':key[0],'ip_position':key[1],'oop_position':key[2],'goals':0,'assists':0,'own_goals':0,'yellow_cards':0,'red_cards':0});item[metric]+=1
        for goal in (events.get('goals',[])if events.get('scorers_verified_against_native_totals')is not False else[]):
            credit(goal['scorer'],'own_goals'if goal['own_goal']else'goals');credit(goal['assist'],'assists')
        for card in (events.get('cards',[])if events.get('cards_verified_against_native_totals')is not False else[]):
            if card['card']in ['yellow','second_yellow']:credit(card['player'],'yellow_cards')
            if card['card']in ['red','second_yellow']:credit(card['player'],'red_cards')
    return {'matches_with_events':available,'unverified_goal_matches':unverified_goals,'unverified_card_matches':unverified_cards,'players':sorted(people.values(),key=lambda p:(-p['goals'],-p['assists'],p['side'],p['native_id'])),'positions':sorted(positions.values(),key=lambda p:(-p['goals'],-p['assists'],p['side'],p['ip_position']))}
