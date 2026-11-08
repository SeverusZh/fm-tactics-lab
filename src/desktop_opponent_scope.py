"""Team-first opponent requests, derived from the save's actual fixture calendar."""
from collections import Counter, defaultdict

PROFILE='team-first-calendar-v1'

def identify(data,club):
    played=set();groups=defaultdict(list)
    for f in data['fixtures']:
        if f.get('home_team_slot')!=0 or f.get('away_team_slot')!=0:continue
        home,away=f.get('home_club_uid'),f.get('away_club_uid')
        if type(home)is not int or type(away)is not int or home==away:continue
        if f.get('played') and club in (home,away):played.add(away if home==club else home)
        if f.get('season_start_year') is not None and f.get('round') is None:
            groups[(f.get('competition_id'),f['stage_id'],f['season_start_year'])].append(f)
    candidates=[]
    for (competition,stage,season),fixtures in groups.items():
        members={f[s+'_club_uid'] for f in fixtures for s in ('home','away')}
        if club not in members or not 4<=len(members)<=40:continue
        pairs=Counter((f['home_club_uid'],f['away_club_uid']) for f in fixtures)
        # Confirm the whole stage, not just a club's cup/group-stage opponents:
        # every ordered pair occurs once in a complete double round robin.
        if len(pairs)!=len(members)*(len(members)-1) or set(pairs.values())!={1}:continue
        dates=[f['date'] for f in fixtures if f.get('date')]
        if not dates:continue
        candidates.append({'competition_id':competition,'stage_id':stage,'season_start_year':season,
            'club_uids':sorted(members),'fixture_count':len(fixtures),'first_date':min(dates),'last_date':max(dates)})
    # Prefer the table whose dates contain the save clock. A save read in the
    # off-season is still inside the season that has just finished or is about
    # to start, so fall back to the latest season rather than losing the league.
    current=[item for item in candidates if item['first_date']<=str(data['date'])<=item['last_date']]
    if not current and candidates:
        latest=max(item['season_start_year'] for item in candidates)
        current=[item for item in candidates if item['season_start_year']==latest]
    # Ambiguous concurrent tables are explicitly unresolved, never guessed.
    league=current[0] if len(current)==1 else None
    members=set(league['club_uids'])-{club} if league else set()
    return {'profile':PROFILE,'played':played,'same_league':members,'league':league,'ambiguous_leagues':current if len(current)>1 else []}

def annotate(report,data,club,scope):
    available={o['club_uid']:o for o in report['opponents']}
    names={c['uid']:c.get('short_name') or c['name'] for c in data['clubs']}
    requested=scope['played']|scope['same_league']
    for o in report['opponents']:
        o.update(has_played=o['club_uid'] in scope['played'],same_league=o['club_uid'] in scope['same_league'],
            plan_policy='coach_preference_preset'if o.get('source_kind')=='coach_preference_preset'else'observed_plan_any_date_same_club')
    report.update(scope_profile=PROFILE,league=scope['league'],league_ambiguous=bool(scope['ambiguous_leagues']),
        same_league_clubs=len(scope['same_league']),same_league_available=len(scope['same_league']&available.keys()),
        requested_teams=[{'club_uid':uid,'name':names.get(uid,str(uid)),'has_played':uid in scope['played'],
            'same_league':uid in scope['same_league'],'available':uid in available,
            'key':available[uid]['key'] if uid in available else None,
            'reason':None if uid in available else ('该队教练偏好预设暂不可用，请查看解析提示'if report.get('source_policy')=='coach_preference_preset'else'该队完整存储方案尚未恢复')}
            for uid in sorted(requested)],plan_policy='coach_preference_preset'if any(o.get('source_kind')=='coach_preference_preset'for o in report['opponents'])else'any_stored_date_same_club')
    report['opponents'].sort(key=lambda o:(not o['same_league'],not o['has_played'],o['club_uid']))
    return report
