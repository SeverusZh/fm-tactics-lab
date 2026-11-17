// Version-bound export of original installation presets and formation codes.
// This mode never generates an AI match plan or restores a career fixture.
static bool desktop_coach_presets_requested(){
 wchar_t enabled[8]={};return GetEnvironmentVariableW(L"FM27_COACH_PRESET_EXPORT",enabled,8)!=0;
}
static void desktop_coach_preset_resource_types(void* resources){
 if(!desktop_coach_presets_requested())return;
 ((void(*)(void*,void*))at(0xc723c0))(resources,at(0x5831a20));
 // Register the style XML field IDs consumed by the original reader.
 struct StyleKey {const char* name;unsigned id;};
 for(auto field:{StyleKey{"tactical_style_id",0x73744944},StyleKey{"description",0x64657363},
                 StyleKey{"attribute_template",0x41747454},StyleKey{"tendency_template",0x54656e54},
                 StyleKey{"preferred_roles",0x5072526f},StyleKey{"features_of_play",0x46744f50},
                 StyleKey{"favoured_attributes",0x46417472},StyleKey{"min",0x6d696e20},StyleKey{"max",0x6d617820}}){
  uintptr_t key[4]={};
  ((void*(*)(void*,const char*,unsigned,unsigned))at(0x9d4f40))(key,field.name,field.id,0);
 }
 uintptr_t key[4]={};
 ((void*(*)(void*,const char*,unsigned,unsigned))at(0x9d4f40))(key,"folder",0x666f6c64,0);
 ((void*(*)(void*,const char*,unsigned,unsigned))at(0x9d4f40))(key,"text",0x74657874,0);
 ((void*(*)(void*,const char*,unsigned,unsigned))at(0x9d4f40))(key,"hint",0x68696e74,0);
 ((void*(*)(void*,const char*,unsigned,unsigned))at(0x9d4f40))(key,"id",0x69642020,0);
}
static void desktop_export_coach_presets(){
 if(!desktop_coach_presets_requested())return;
 // Isolated diagnostic only. Resolve the original installation's FMF root,
// then bind the match_folder symbol specified by special folders.xml.
// 7a4310 is the original SYMBOL-keyed tree insertion used by this image;
// key/value layout is checked before retaining the original FILE object.
{
 auto fm=*(unsigned char**)at(0x580eb38);
 if(!fm)desktop_finish_and_exit(248);
 void* existing=nullptr;
 ((void*(*)(void*,void*,void*))at(0xc6a290))(fm,&existing,at(0x582dd78));
 fprintf(log_file,"{\"event\":\"match_folder_binding_before\",\"present\":%s}\n",existing?"true":"false");fflush(log_file);
 if(!existing){
  auto root=desktop_game_root.empty()?bundle:desktop_game_root;
  auto utf=(root/"shared/data/simatch.fmf").generic_u8string();
  uintptr_t path[4]={};
  ((void*(*)(void*,const char*,int))at(0x122880))(path,utf.c_str(),-1);
  void* file=nullptr;void* folder=nullptr;
  auto resources=*(unsigned char**)at(0x580eb40);
  ((void*(*)(void*,void*,void*))at(0x39f72a0))(&file,path,resources+0xc0);
  ((void*(*)(void*,void*,uintptr_t))at(0x148bac0))(&folder,&file,*(uintptr_t*)at(0x5824c90));
  if(!folder)desktop_finish_and_exit(248);
  auto impl=*(unsigned char**)(fm+0x18);
  auto tree=*(unsigned char**)(impl+8);
  uintptr_t iter[2]={};
  ((void*(*)(void*,void*,void*))at(0x7bd250))(tree,iter,at(0x582dd78));
  auto node=(unsigned char*)iter[0];
  if(!node||*(uintptr_t*)(node+0x20)!=*(uintptr_t*)at(0x582dd78)||*(void**)(node+0x28))desktop_finish_and_exit(248);
  InterlockedIncrement((volatile LONG*)((unsigned char*)folder+8));
  *(void**)(node+0x28)=folder;
  void* found=nullptr;
  ((void*(*)(void*,void*,void*))at(0xc6a290))(fm,&found,at(0x582dd78));
  if(found!=folder)desktop_finish_and_exit(248);
  fprintf(log_file,"{\"event\":\"match_folder_bound\",\"source\":\"installation_FMF\",\"native_type\":\"%s\"}\n",native_type((unsigned char*)folder));fflush(log_file);
 }
}

 auto loader=((unsigned char*(*)())at(0x1ecc30))();
 ((void(*)(void*,unsigned))at(0xe61f50))(loader,0);
 auto sb=*(unsigned char***)(loader+8),se=*(unsigned char***)(loader+0x10);
 if(se<sb||se-sb>128)desktop_finish_and_exit(248);
 for(auto p=sb;p!=se;p++)fprintf(log_file,"{\"event\":\"coach_preset_style\",\"id\":%u,\"style_code\":%u}\n",(*p)[0xc8],*(uint32_t*)(*p+4));
 // Read the already-loaded original TAC objects; do not generate a plan.
{
 auto loader=*(unsigned char**)at(0x580ebf8);if(!loader)desktop_finish_and_exit(248);
 auto begin=*(unsigned char***)(loader+0x20),end=*(unsigned char***)(loader+0x28);
 if(end<begin||end-begin>512)desktop_finish_and_exit(248);
 for(auto entry=begin;entry!=end;entry++){
  auto plan=*entry;auto name=*(unsigned char**)(plan+0xf8);unsigned size=name?*(unsigned*)name:0;if(size>1024)desktop_finish_and_exit(248);
  fprintf(log_file,"{\"event\":\"installed_tactic_preset\",\"index\":%u,\"style_code\":%u,\"name_utf8_hex\":\"",(unsigned)(entry-begin),*(uint32_t*)(plan+0x100));
  for(unsigned i=0;i<size;i++)fprintf(log_file,"%02x",name[4+i]);
  fprintf(log_file,"\",\"mentality\":%u,\"team_bits\":\"",plan[0x105]);
  for(unsigned i=0;i<16;i++)fprintf(log_file,"%02x",plan[0xe0+i]);fputs("\",\"mapping\":[",log_file);
  for(unsigned i=0;i<11;i++)fprintf(log_file,"%s%u",i?",":"",plan[0x79c+i]);fputs("],\"phases\":[",log_file);
  for(unsigned phase=0;phase<2;phase++){
   fprintf(log_file,"%s[",phase?",":"");
   for(unsigned i=0;i<11;i++){
    auto cell=plan+(phase?0x438:0x118)+0x48*i;auto pi=instruction_entry(cell,false);
    fprintf(log_file,"%s{\"position\":%u,\"role_flags\":\"%llu\",\"pi_flags\":\"%llu\",\"target_player\":%u,\"target_position\":%u}",i?",":"",*(uint32_t*)cell,*(unsigned long long*)(cell+0x40),pi?pi[1]:0,pi?((unsigned char*)pi)[20]:255,pi?*(uint32_t*)((unsigned char*)pi+16):0);
   }fputs("]",log_file);
  }fputs("]}\n",log_file);fflush(log_file);
 }
}

 unsigned formations=0;
 for(unsigned code=0;code<=69;code++){
  const auto first=*reinterpret_cast<uintptr_t*>(at(0x5833cc0));
  const auto last=*reinterpret_cast<uintptr_t*>(at(0x5833cc8));
  // The native reader uses a built-in predicate before the dynamic table exists.
  const auto ordinal=code-1u;
  const bool builtin=code>0&&ordinal<=68&&(ordinal>=49||!(0x19c1000011001ULL>>ordinal&1));
  const bool valid=first!=last?((unsigned char(*)(unsigned))at(0x3a36a40))(code)!=0:builtin;
  if(!valid)continue;
  auto plan=(unsigned char*)calloc(1,0x7a8);
  ((void*(*)(void*,void*,unsigned char))at(0x18b080))(plan,at(0x4c015d9),1);
  ((void(*)(void*,unsigned,unsigned char,unsigned char,unsigned char))at(0x1281c0))(plan,code,0,1,1);
  fprintf(log_file,"{\"event\":\"coach_preset_formation\",\"code\":%u,\"positions\":[",code);
  for(unsigned j=0;j<11;j++)fprintf(log_file,"%s%u",j?",":"",*(uint32_t*)(plan+0x118+0x48*j));
  fputs("]}\n",log_file);fflush(log_file);formations++;
  ((void(*)(void*))at(0x69520))(plan);free(plan);
 }
 fprintf(log_file,"{\"event\":\"coach_preset_export_complete\",\"styles\":%u,\"templates\":%u,\"formations\":%u}\n",(unsigned)(se-sb),(unsigned)((*(unsigned char***)(loader+0x28))-(*(unsigned char***)(loader+0x20))),formations);fflush(log_file);
 desktop_finish_and_exit(0);
}
