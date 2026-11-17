// Opt-in execution inputs: process trampolines persist, match bindings do not.
// Current image 2494687: 71370 computes the 33-byte tactical-effectiveness
// record at MATCH_PLAYER+cba. 465b0 consumes it during action sampling.
static unsigned char* execution_teams[2]={};
static int execution_policy[2]={-1,-1};
enum ExecutionComponent {Understanding, BuyIn, Opposition, Ability, ComponentCount};
static int execution_components[2][ComponentCount]={{-1,-1,-1,-1},{-1,-1,-1,-1}};
static unsigned long long execution_builds[2]={},execution_samples[2]={};
static unsigned short execution_input_ca[2][26]={};
static bool execution_input_seen[2][26]={};
static unsigned char execution_calculated_overall[2][26]={};
static unsigned char execution_applied_record[2][26][34]={};
static unsigned execution_player_samples[2][26]={};
using ExecutionBuild=void(*)(void*,void*,void*,void*,void*,void*,void*,void*,void*,unsigned short);
using ExecutionSample=void(*)(void*,uintptr_t,uintptr_t,void*,uintptr_t);
static ExecutionBuild execution_original_build=nullptr;
static ExecutionSample execution_original_sample=nullptr;
static bool execution_active=false;
static void execution_reset_match(){
 execution_active=false;memset(execution_teams,0,sizeof(execution_teams));
 for(unsigned side=0;side<2;side++){
  execution_policy[side]=-1;for(auto& value:execution_components[side])value=-1;
 }
 memset(execution_builds,0,sizeof(execution_builds));memset(execution_samples,0,sizeof(execution_samples));
 memset(execution_input_ca,0,sizeof(execution_input_ca));memset(execution_input_seen,0,sizeof(execution_input_seen));
 memset(execution_calculated_overall,0,sizeof(execution_calculated_overall));
 memset(execution_applied_record,0,sizeof(execution_applied_record));
 memset(execution_player_samples,0,sizeof(execution_player_samples));
}
static void execution_end_match(){
 execution_active=false;memset(execution_teams,0,sizeof(execution_teams));
 fputs("{\"event\":\"native_execution_context_cleared\",\"team_bindings_cleared\":true}\n",log_file);fflush(log_file);
}

static int execution_side(unsigned char* player){
 if(!execution_active)return -1;
 auto team=*(unsigned char**)(player+0x288);
 return !team?-1:team==execution_teams[0]?0:team==execution_teams[1]?1:-1;
}
static int execution_ability_from_components(unsigned raw,unsigned role,const int* components){
 if(components[Ability]>=0)return components[Ability];
 // The original builder derives these two bytes from CA and the IP/OOP role
 // evaluations. Reuse them and the original float operation order.
 const float effective=raw*4.0f;
 const float suitability=(role*2.0f)/100.0f;
 return (int)(effective*suitability*100.0f/800.0f+0.5f);
}
static int execution_ability(const unsigned char* player,const int* components){
 return execution_ability_from_components(player[0xcd6],player[0xcd7],components);
}
static int execution_overall(const unsigned char* player,const int* components){
 return (50*components[Understanding]+25*components[BuyIn]+15*components[Opposition]+10*execution_ability(player,components)+50)/100;
}
static void execution_apply(unsigned char* player,int side){
 if(side<0)return;
 if(execution_policy[side]>=0){
  memset(player+0xcba,execution_policy[side],33);
  return;
 }
 const auto components=execution_components[side];
 if(components[Understanding]<0)return;
 // Override the four inputs to the overall score. Only buy-in and opposition
 // information also have their own final fields read by the sampler.
 player[0xcd8]=(unsigned char)execution_overall(player,components);
 player[0xcd9]=(unsigned char)components[BuyIn];
 player[0xcda]=(unsigned char)components[Opposition];
}
static void execution_build(void* record,void* plan,void* history,void* exposure,void* attributes,
                            void* opposition,void* training,void* ip,void* oop,unsigned short ca){
 execution_original_build(record,plan,history,exposure,attributes,opposition,training,ip,oop,ca);
 auto player=(unsigned char*)record-0xcba;int side=execution_side(player);
 if(side<0)return;
 execution_builds[side]++;
 const auto calculated_overall=player[0xcd8];
 execution_apply(player,side);
 for(unsigned i=0;i<26;i++)if(original_roster[side][i]==player){
  execution_input_ca[side][i]=ca;
  execution_input_seen[side][i]=true;
  execution_calculated_overall[side][i]=calculated_overall;
  if(!execution_player_samples[side][i])memcpy(execution_applied_record[side][i],player+0xcba,34);
  break;
 }
}
static void execution_sample(void* actor,uintptr_t a,uintptr_t b,void* rng,uintptr_t c){
 auto player=(unsigned char*)actor;int side=execution_side(player);
 execution_apply(player,side);
 if(side>=0){
  execution_samples[side]++;
  if(execution_policy[side]>=0)for(unsigned i=0;i<33;i++)
   if(player[0xcba+i]!=execution_policy[side])desktop_finish_and_exit(245);
  const auto components=execution_components[side];
  if(components[Understanding]>=0&&(player[0xcd8]!=execution_overall(player,components)
      ||player[0xcd9]!=components[BuyIn]||player[0xcda]!=components[Opposition]))desktop_finish_and_exit(245);
  for(unsigned i=0;i<26;i++)if(original_roster[side][i]==player){
   if(!execution_input_seen[side][i])execution_input_ca[side][i]=*(uint16_t*)(player+0xc98);
   memcpy(execution_applied_record[side][i],player+0xcba,34);
   execution_player_samples[side][i]++;
   break;
  }
 }
 execution_original_sample(actor,a,b,rng,c);
}
static void* execution_redirect(unsigned rva,void* replacement,unsigned stack_low,unsigned stack_high){
 // Both entries have exactly eight pushes and a seven-byte SUB RSP prologue;
 // no RIP-relative instruction or branch is relocated into the trampoline.
 unsigned char expected[]={0x41,0x57,0x41,0x56,0x41,0x55,0x41,0x54,0x56,0x57,0x55,0x53,
                            0x48,0x81,0xec,(unsigned char)stack_low,(unsigned char)stack_high,0,0};
 auto entry=(unsigned char*)at(rva);
 if(memcmp(entry,expected,sizeof(expected)))desktop_finish_and_exit(246);
 auto trampoline=(unsigned char*)VirtualAlloc(nullptr,64,MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
 if(!trampoline)desktop_finish_and_exit(247);
 memcpy(trampoline,entry,19);
 unsigned char jump[]={0xff,0x25,0,0,0,0,0,0,0,0,0,0,0,0};
 auto continuation=entry+19;memcpy(jump+6,&continuation,8);memcpy(trampoline+19,jump,14);
 DWORD old=0;if(!VirtualProtect(trampoline,64,PAGE_EXECUTE_READ,&old))desktop_finish_and_exit(247);
 FlushInstructionCache(GetCurrentProcess(),trampoline,64);
 memcpy(jump+6,&replacement,8);
 if(!VirtualProtect(entry,19,PAGE_EXECUTE_READWRITE,&old))desktop_finish_and_exit(247);
 memcpy(entry,jump,14);memset(entry+14,0x90,5);
 DWORD unused;if(!VirtualProtect(entry,19,old,&unused))desktop_finish_and_exit(247);
 FlushInstructionCache(GetCurrentProcess(),entry,19);return trampoline;
}
static void execution_install(unsigned char* match){
 execution_reset_match();
 bool enabled=false;
 for(const auto& edit:scenario_edits){
  if(edit.kind!=61)continue;
  if(edit.side>1||edit.a>ComponentCount||edit.b||edit.value>100)desktop_finish_and_exit(244);
  auto& slot=edit.a?execution_components[edit.side][edit.a-1]:execution_policy[edit.side];
  if(slot>=0)desktop_finish_and_exit(244);
  slot=(int)edit.value;
  enabled=true;
 }
 if(!enabled)return;
 for(unsigned side=0;side<2;side++){
  const auto c=execution_components[side];
  if(execution_policy[side]>=0){
   for(int value:execution_components[side])if(value>=0)desktop_finish_and_exit(244);
  }else if(c[Understanding]<0||c[BuyIn]<0||c[Opposition]<0)desktop_finish_and_exit(244);
 }
 if(strcmp(native_image_sha256,
    "8c6971ce0b1c8afe6529ea3f46205a5175aea988a97d7421a980da42e23fe340"))desktop_finish_and_exit(244);
 execution_active=true;
 for(unsigned side=0;side<2;side++)execution_teams[side]=*(unsigned char**)(match+0x15380+8*side);
 constexpr unsigned version=0x1b000000u;
 fprintf(log_file,"{\"event\":\"experimental_engine_version\",\"before\":%u,\"after\":%u,\"production_supported\":false}\n",*(unsigned*)(match+0xa3a),version);
 *(unsigned*)(match+0xa3a)=version;
 bool reused=execution_original_sample!=nullptr;
 if(!reused){
  execution_original_build=(ExecutionBuild)execution_redirect(0x71370,(void*)execution_build,0x38,1);
  execution_original_sample=(ExecutionSample)execution_redirect(0x465b0,(void*)execution_sample,0x88,0);
 }
 fprintf(log_file,"{\"event\":\"native_execution_context_bound\",\"hooks_reused\":%s,\"match_inputs_reset\":true}\n",reused?"true":"false");fflush(log_file);
}
static void execution_snapshot(unsigned char* match,const char* stage){
 if(!execution_active)return;
 for(unsigned side=0;side<2;side++){
  auto team=*(unsigned char**)(match+0x15380+8*side);
  fprintf(log_file,"{\"event\":\"native_execution_probe\",\"stage\":\"%s\",\"side\":%u,\"policy\":",stage,side);
  if(execution_policy[side]>=0)fprintf(log_file,"%d",execution_policy[side]);
  else{
   const auto c=execution_components[side];
   fprintf(log_file,"{\"understanding\":%d,\"buy_in\":%d,\"opposition\":%d",
           c[Understanding],c[BuyIn],c[Opposition]);
   if(c[Ability]>=0)fprintf(log_file,",\"ability\":%d",c[Ability]);
   fputc('}',log_file);
  }
  fprintf(log_file,",\"build_calls\":%llu,\"sample_calls\":%llu,\"players\":[",execution_builds[side],execution_samples[side]);
  // An early departure can leave an action sample without a builder call.
  // Include the record actually applied by either hook.
  bool first=true;
  for(unsigned i=0;i<team[0x72d];i++){
   if(!execution_input_seen[side][i]&&!execution_player_samples[side][i])continue;
   const auto record=execution_applied_record[side][i];
   fprintf(log_file,"%s{\"slot\":%u,\"overall\":%u,\"buy_in\":%u,\"next_match_information\":%u,\"raw_ability_component\":%u,\"role_suitability_component\":%u,",first?"":",",i,record[30],record[31],record[32],record[28],record[29]);
   first=false;
   if(execution_policy[side]<0)fprintf(log_file,"\"ability_contribution\":%d,",execution_ability_from_components(record[28],record[29],execution_components[side]));
   fprintf(log_file,"\"input_roster_slot\":%u,\"input_ca\":%u,\"player_sample_calls\":%u,",i,execution_input_ca[side][i],execution_player_samples[side][i]);
   if(execution_input_seen[side][i])fprintf(log_file,"\"calculated_overall_before_override\":%u,",execution_calculated_overall[side][i]);
   fputs("\"record_hex\":\"",log_file);
   for(unsigned j=0;j<34;j++)fprintf(log_file,"%02x",record[j]);fputs("\"}",log_file);
  }
  fputs("]}\n",log_file);fflush(log_file);
 }
}
