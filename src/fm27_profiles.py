"""Bounded extra player inputs, independently checked against native recordings."""
# ID, minimum, maximum. No user-supplied addresses or arbitrary memory writes.
FIELDS={
 'height_cm':(0,140,220),'age':(1,14,60),
 'professionalism':(2,1,20),'loyalty':(3,1,20),'sportsmanship':(4,1,20),
 'temperament':(5,1,20),'pressure':(6,1,20),'ambition':(7,1,20),'adaptability':(8,1,20),
 'traits_low':(9,0,0xffffffff),'traits_high':(10,0,0xffffffff),
 'current_ability':(11,0,200),'home_reputation':(12,0,10000),'current_reputation':(13,0,10000),'world_reputation':(14,0,10000),
 'condition':(15,0,10000),'sharpness':(16,0,10000),'sharpness_secondary':(17,0,10000),
 'fatigue_raw':(18,0,65535),'weight_kg':(19,40,140),
 'team_cohesion':(20,0,100),'club_cohesion':(21,0,100),'morale':(22,1,20),
}
def normalize(data):
 if not isinstance(data,dict)or set(data)-set(FIELDS):raise ValueError('未知球员扩展输入')
 result={}
 for key,value in data.items():
  _,lo,hi=FIELDS[key]
  if type(value)is not int or not lo<=value<=hi:raise ValueError('球员扩展输入范围无效: '+key)
  result[key]=value
 return result

# Controlled initial state, applied to both complete rosters before preparation.
CONTROLLED_START={"condition":10000,"sharpness":10000,"sharpness_secondary":10000,"fatigue_raw":0,"team_cohesion":80,"club_cohesion":100,"morale":20}
