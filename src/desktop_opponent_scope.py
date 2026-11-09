"""Team-first opponent requests, derived from the save's actual fixture calendar."""
from collections import Counter, defaultdict
from datetime import date, timedelta

PROFILE='team-first-calendar-v3'
PRESEASON_WINDOW = timedelta(days=90)

def identify(data,club):
    played=set();groups=defaultdict(list)
    for f in data['fixtures']:
        if f.get('home_team_slot')!=0 or f.get('away_team_slot')!=0:continue
        home,away=f.get('home_club_uid'),f.get('away_club_uid')
        if type(home)is not int or type(away)is not int or home==away:continue
        if f.get('played') and club in (home,away):played.add(away if home==club else home)
        if f.get('season_start_year') is not None and f.get('round') is None:
            groups[(f.get('competition_id'),f['stage_id'],f['season_start_year'])].append(f)
    save_date = date.fromisoformat(data['date'])
    active, preseason, postseason = [], [], []
    for (competition,stage,season),fixtures in groups.items():
        members={f[s+'_club_uid'] for f in fixtures for s in ('home','away')}
        if club not in members or not 4<=len(members)<=40:continue
        pairs=Counter((f['home_club_uid'],f['away_club_uid']) for f in fixtures)
        # Confirm the whole stage, not just a club's cup/group-stage opponents:
        # every ordered pair occurs once in a complete double round robin.
        if len(pairs)!=len(members)*(len(members)-1) or set(pairs.values())!={1}:continue
        dates=[f['date'] for f in fixtures if f.get('date')]
        if not dates:continue
        first, last = min(dates), max(dates)
        candidate = {'competition_id':competition,'stage_id':stage,'season_start_year':season,
            'club_uids':sorted(members),'fixture_count':len(fixtures),'first_date':first,'last_date':last}
        if first <= data['date'] <= last:
            active.append(candidate)
        elif timedelta(0) < date.fromisoformat(first) - save_date <= PRESEASON_WINDOW:
            preseason.append(candidate)
        elif timedelta(0) < save_date - date.fromisoformat(last) <= PRESEASON_WINDOW:
            postseason.append(candidate)
    # Prefer an active or upcoming season before a recently completed table.
    candidates = active or preseason or postseason
    league=candidates[0] if len(candidates)==1 else None
    members=set(league['club_uids'])-{club} if league else set()
    return {'profile':PROFILE,'played':played,'same_league':members,'league':league,'ambiguous_leagues':candidates if len(candidates)>1 else []}

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
