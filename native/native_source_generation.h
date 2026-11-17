static unsigned char duel_competition_defaults[0x30]={};
// A fresh controlled desktop duel. Source league identities choose opponents;
// runtime uses original fresh competition defaults, not a career fixture replay.
static std::vector<unsigned char> generation_source;
static void source_generation_install(unsigned char* match){
    generation_source=source_generation_config;if(generation_source.empty())return;
    if(generation_source.size()!=8+2*288||memcmp(generation_source.data(),"FM27DUL1",8))desktop_finish_and_exit(230);
    {
        memcpy(match+0x678,duel_competition_defaults,0x30);
        fputs("{\"event\":\"native_fresh_duel_competition_context\",\"original_constructor_defaults\":true,\"carrier_competition_discarded\":true}\n",log_file);
    }
    for(unsigned side=0;side<2;side++){
        auto p=generation_source.data()+8+288*side;
        if(*(uint32_t*)(p+272)>1||*(uint32_t*)(p+8)>10000||*(uint16_t*)(p+194)>32)desktop_finish_and_exit(230);
        for(unsigned i=0;i<52;i++)if(p[16+i]>100)desktop_finish_and_exit(230);
        for(unsigned i=0;i<8;i++)if(p[68+i]>69||p[76+i]>(i==7?100:20))desktop_finish_and_exit(230);
        for(unsigned i=0;i<5;i++)if(*(uint16_t*)(p+176+2*i)>(i>=3?200:10000))desktop_finish_and_exit(230);
        auto team=*(unsigned char**)(match+0x15380+8*side);auto manager=*(unsigned char**)(team+0x630);
        unsigned count=*(uint32_t*)(p+12);if(count<11||count>23)desktop_finish_and_exit(230);
        // Original constructors/assignment prevent carrier PI maps or phase
        // permutations from surviving into a newly generated source plan.
        if(!*(uint32_t*)(p+272)){
        for(unsigned i=0;i<26;i++)set_oi(manager+0x16f8+3*i,0x80000);
        manager[0x1748]=0;
        for(unsigned id=1;id<=11;id++)if(auto list=priority_list(manager,id))*(void**)(list+8)=*(void**)list;
        auto fresh=(unsigned char*)calloc(1,0x7a8);
        ((void*(*)(void*,void*,unsigned char))at(0x18b080))(fresh,at(0x4c015d9),1);
        ((void*(*)(void*,void*))at(0x1484e0))(manager+0x1818,fresh);
        ((void(*)(void*))at(0x69520))(fresh);free(fresh);
        }
        *(uint32_t*)(team+0x2c)=*(uint32_t*)p;*(uint16_t*)(team+0x11e)=(uint16_t)*(uint32_t*)(p+8);
        *(uint32_t*)(manager+0x50)=*(uint32_t*)(p+4);
        memcpy(manager+0x2fc8,p+16,52);memcpy(manager+0x3098,p+68,8);memcpy(manager+0x72,p+76,8);
        memcpy(manager+0x30b2,p+176,10);memcpy(manager+0x30c1,p+186,7);manager[0x30c0]=p[193];
        auto traits=*(uint16_t*)(p+194);if(traits>32)desktop_finish_and_exit(230);
        auto trait_memory=(unsigned char*)((void*(*)(void*,size_t))at(0xc03d0))(*(void**)at(0x580eaf0),(traits?traits:1)*2);
        memcpy(trait_memory,p+196,traits*2);*(void**)(manager+0x3000)=trait_memory;*(void**)(manager+0x3008)=trait_memory+traits*2;*(void**)(manager+0x3010)=trait_memory+(traits?traits:1)*2;
        *(uint32_t*)(manager+0x30a0)=0x24000u|*(uint32_t*)(p+272);
        *(uint32_t*)(team+0xd4)=*(uint32_t*)(p+276);
        // Preserve the explicit common match environment for now. These source
        // identity fields are verified; competition/rules admission is separate.
        auto flags=(uint16_t*)(team+0x136);
        *flags=(*flags&~3u)|(*(uint32_t*)(p+280)!=0xffffffff?1u:0u)|(*(uint32_t*)(p+284)!=0xffffffff?2u:0u);
        for(unsigned i=0;i<count;i++){
            auto actor=original_roster[side][i];*(uint32_t*)(actor+0x50)=*(uint32_t*)(p+84+4*i);
            // Original 127fc0 binds a new statistics record only for starters.
            // A fresh duel must discard a recording/previous-worker bench
            // record before original preparation and substitution binding.
            *(void**)(actor+0x1880)=nullptr;
            *(void**)(actor+0x1530)=nullptr;
        }
        for(unsigned i=count;i<26;i++){
            auto actor=original_roster[side][i];if(!actor)continue;
            *(uint32_t*)(actor+0x50)=0xffffffff;*(void**)(actor+0x1880)=nullptr;*(void**)(actor+0x1530)=nullptr;
        }
        // Rebind the source captains by native player UID. Carrier person keys
        // remain opaque handles, so never use old priority lists by slot.
        auto list=priority_list(manager,0);*(void**)(list+8)=*(void**)list;
        *(uint32_t*)(manager+0x8e8)=0x4e554c4c;
        for(unsigned choice=0;choice<2;choice++){
            auto uid=*(uint32_t*)(p+280+4*choice);
            for(unsigned i=0;i<count;i++){
                auto actor=*(unsigned char**)(team+0x138+8*i);
                if(*(uint32_t*)(actor+0x50)!=uid)continue;
                auto key=person_key(actor);
                ((void(*)(void*,uint32_t,const uint32_t*,size_t))at(0x4bcffd0))(list,0xffffffff,&key,1);
                if(i<11&&*(uint32_t*)(manager+0x8e8)==0x4e554c4c)*(uint32_t*)(manager+0x8e8)=key;
            }
        }
        // AI selects from the bench during preparation, so eligibility must
        // already exclude every carrier player before the original AI runs.
        team[0x72d]=(unsigned char)count;
        // 72e is the registered match roster used by original 127990 to
        // allocate canonical player statistics, not the eleven phase cells.
        // Both roster counts must describe this source-backed duel.
        team[0x72e]=(unsigned char)count;
        fprintf(log_file,"{\"event\":\"source_generation_installed\",\"side\":%u,\"club_uid\":%u,\"coach_uid\":%u,\"reputation\":%u,\"players\":%u,\"context_complete\":false,\"tail_hex\":\"",side,*(uint32_t*)p,*(uint32_t*)(p+4),*(uint32_t*)(p+8),count);
        for(unsigned i=0;i<7;i++)fprintf(log_file,"%02x",manager[0x30c1+i]);fputs("\"}\n",log_file);fflush(log_file);
    }

}
static void source_generation_verified(unsigned char* match){
    if(generation_source.empty())return;
    // Original d1180 deliberately adapts three staff preferences to the current
    // players and opposing coach. Replay it on isolated copies, in home/away
    // preparation order, rather than demanding immutable effective preferences.
    unsigned char* expected_manager[2]={};unsigned char* expected_team[2]={};
    for(unsigned side=0;side<2;side++){
        auto team=*(unsigned char**)(match+0x15380+8*side);auto manager=*(unsigned char**)(team+0x630);
        expected_manager[side]=(unsigned char*)malloc(0x3500);memcpy(expected_manager[side],manager,0x3500);
        expected_team[side]=(unsigned char*)calloc(1,0x740);*(void**)(expected_team[side]+0x630)=expected_manager[side];
        memcpy(expected_manager[side]+0x30c1,generation_source.data()+8+288*side+186,7);
    }
    for(unsigned side=0;side<2;side++)*(void**)(expected_manager[side]+0x290)=expected_team[1-side];
    for(unsigned side=0;side<2;side++)if(!*(uint32_t*)(generation_source.data()+8+288*side+272))((void(*)(void*))at(0x6a370))(expected_manager[side]);
    wchar_t output[32768]={};GetEnvironmentVariableW(L"FM27_SOURCE_PLAN_DIRECTORY",output,32768);
    for(unsigned side=0;side<2;side++){
        auto p=generation_source.data()+8+288*side;
        auto team=*(unsigned char**)(match+0x15380+8*side);auto manager=*(unsigned char**)(team+0x630);auto count=*(uint32_t*)(p+12);
        auto check=[&](const char* field,unsigned char* actual,const unsigned char* expected,unsigned n){
            if(!memcmp(actual,expected,n))return;
            fprintf(log_file,"{\"event\":\"source_generation_mismatch\",\"side\":%u,\"field\":\"%s\",\"actual\":\"",side,field);
            for(unsigned i=0;i<n;i++)fprintf(log_file,"%02x",actual[i]);fputs("\",\"expected\":\"",log_file);for(unsigned i=0;i<n;i++)fprintf(log_file,"%02x",expected[i]);fputs("\"}\n",log_file);fflush(log_file);desktop_finish_and_exit(232);
        };
        check("source_nation",team+0xd4,p+276,4);check("club_uid",team+0x2c,p,4);check("club_reputation",team+0x11e,p+8,2);check("coach_uid",manager+0x50,p+4,4);
        check("coaching_parameters",manager+0x2fc8,p+16,52);check("formation_preferences",manager+0x3098,p+68,8);check("coach_personality",manager+0x72,p+76,8);
        check("coach_reputations",manager+0x30b2,p+176,10);check("native_adapted_coach_preferences",manager+0x30c1,expected_manager[side]+0x30c1,7);check("coach_influence",manager+0x30c0,p+193,1);
        for(unsigned i=0;i<count;i++)if(*(uint32_t*)(original_roster[side][i]+0x50)!=*(uint32_t*)(p+84+4*i))desktop_finish_and_exit(232);
        for(unsigned i=0;i<count;i++){
            auto actor=*(unsigned char**)(team+0x138+8*i);auto stats=*(unsigned char**)(actor+0x1880);
            if(stats&&(stats[0x8b]||stats[0xa6]||stats[0xa7]))desktop_finish_and_exit(235);
        }
        fprintf(log_file,"{\"event\":\"source_fresh_player_statistics_verified\",\"side\":%u,\"players\":%u,\"goals_yellow_red_zero\":true}\n",side,count);
        fprintf(log_file,"{\"event\":\"source_generation_readback\",\"side\":%u,\"staff_player_identity_and_attributes_verified\":true,\"mentality\":%u,\"team_bits\":\"",side,manager[0x191d]);
        for(unsigned i=0;i<16;i++)fprintf(log_file,"%02x",manager[0x18f8+i]);fputs("\",\"mapping\":[",log_file);
        for(unsigned i=0;i<11;i++)fprintf(log_file,"%s%u",i?",":"",manager[0x1fb4+i]);fputs("],\"phases\":[",log_file);
        for(unsigned phase=0;phase<2;phase++){
            fprintf(log_file,"%s[",phase?",":"");
            for(unsigned i=0;i<11;i++){
                auto cell=manager+(phase?0x1c50:0x1930)+i*0x48;auto pi=instruction_entry(cell,false);
                fprintf(log_file,"%s{\"position\":%u,\"role_flags\":\"%llu\",\"pi_flags\":\"%llu\",\"target_player\":%u,\"target_position\":%u}",i?",":"",*(uint32_t*)cell,*(unsigned long long*)(cell+0x40),pi?pi[1]:0,pi?((unsigned char*)pi)[20]:255,pi?*(uint32_t*)((unsigned char*)pi+16):0);
            }fputs("]",log_file);
        }
        fputs("],\"native_adaptation_verified\":true,\"effective_coach_tail_hex\":\"",log_file);
        for(unsigned i=0;i<7;i++)fprintf(log_file,"%02x",manager[0x30c1+i]);fputs("\",\"lineup_source_uids\":[",log_file);
        for(unsigned i=0;i<11;i++){auto actor=*(unsigned char**)(team+0x138+8*i);fprintf(log_file,"%s%u",i?",":"",*(uint32_t*)(actor+0x50));}
        fprintf(log_file,"],\"strength_context\":[%.9g,%.9g,%.9g],\"full_opponent_recovered\":false}\n",*(float*)(manager+0x34c4),*(float*)(manager+0x34c8),*(float*)(manager+0x34cc));fflush(log_file);
        if(!output[0])continue;
        std::vector<unsigned char> bytes;void* methods[8]={};methods[2]=(void*)desktop_write_tell;methods[3]=(void*)desktop_write_seek;methods[5]=(void*)desktop_tac_write;
        DesktopTacticWriter writer={methods,0,0,0,&bytes,0};void* reference=&writer;
        auto accepted=((unsigned char(*)(void*,void**,unsigned char))at(0x1b8bfc0))(manager+0x1818,&reference,1);
        if(!accepted||writer.error||bytes.empty())desktop_finish_and_exit(233);
        std::ofstream file(fs::path(output)/(std::to_string(side)+".tac"),std::ios::binary);file.write((char*)bytes.data(),bytes.size());file.flush();if(!file)desktop_finish_and_exit(233);
    }
    for(unsigned side=0;side<2;side++){free(expected_manager[side]);free(expected_team[side]);}
}
