// Schema 26, build 2493426. Original sub-readers; symbolic identities stay IDs.
static void desktop_read_ai_tactics(unsigned char* match){
    wchar_t path[32768]={};if(!GetEnvironmentVariableW(L"FM27_AI_TACTICS_SECTION",path,32768))return;
    std::ifstream file(path,std::ios::binary);std::vector<unsigned char> bytes((std::istreambuf_iterator<char>(file)),{});
    if(bytes.size()<20||bytes.size()>32*1024*1024)desktop_finish_and_exit(197);
    void* methods[8]={};methods[2]=(void*)desktop_tac_tell;methods[3]=(void*)desktop_tac_seek;methods[5]=(void*)desktop_tac_read;
    DesktopTacticStream stream={methods,0x200000001ULL,0,0,bytes.data(),bytes.size(),0};void* reference=&stream;
    *(unsigned char*)at(0x58204dc)=1;
    if(memcmp(bytes.data(),"\x03\x01tad.\x1a\0",8))desktop_finish_and_exit(197);
    unsigned count=*(uint16_t*)(bytes.data()+8);stream.cursor=10;if(count>128)desktop_finish_and_exit(197);
    for(unsigned i=0;i<count;i++){
        if(stream.cursor+5>stream.size)desktop_finish_and_exit(197);
        unsigned revision=bytes[stream.cursor++],person=*(uint32_t*)(bytes.data()+stream.cursor);stream.cursor+=4;
        if(revision!=13)desktop_finish_and_exit(197);
        unsigned char object[0xb0]={};((void*(*)(void*))at(0x3634a00))(object);
        auto okay=((unsigned char(*)(void*,void**))at(0xf0000000))(object,&reference);
        fprintf(log_file,"{\"event\":\"ai_manager_tree\",\"person\":%u,\"accepted\":%s,\"offset\":%llu,\"error\":%u}\n",person,okay?"true":"false",(unsigned long long)stream.cursor,stream.error);fflush(log_file);
        if(!okay||stream.error)desktop_finish_and_exit(197);
        auto head=*(unsigned char**)object;auto node=*(unsigned char**)head;unsigned visited=0;
        while(node!=head){
            if(++visited>4096)desktop_finish_and_exit(197);
            auto begin=*(unsigned char***)(node+0x1038),end=*(unsigned char***)(node+0x1040);
            if(end<begin||end-begin>22)desktop_finish_and_exit(197);
            fprintf(log_file,"{\"event\":\"ai_manager_team_ref\",\"person_selector\":%u,\"team_id\":%u,\"full_plan_count\":%llu,\"active_plan_index\":%u}\n",person,*(uint32_t*)(node+0x20),(unsigned long long)(end-begin),node[0x1050]);fflush(log_file);
            if(!node[0x19]&& !(*(unsigned char**)(node+0x10))[0x19]){node=*(unsigned char**)(node+0x10);while(!(*(unsigned char**)node)[0x19])node=*(unsigned char**)node;}
            else{auto parent=*(unsigned char**)(node+8);while(!parent[0x19]&&node==*(unsigned char**)(parent+0x10)){node=parent;parent=*(unsigned char**)(parent+8);}node=parent;}
        }
        auto member=[&](const char* name,bool accepted){fprintf(log_file,"{\"event\":\"ai_member\",\"name\":\"%s\",\"accepted\":%s,\"offset\":%llu,\"error\":%u}\n",name,accepted?"true":"false",(unsigned long long)stream.cursor,stream.error);fflush(log_file);if(!accepted||stream.error)desktop_finish_and_exit(197);};
        member("plan_vector",((unsigned char(*)(void*,void**))at(0x1b77700))(object+0x58,&reference));
        member("reference_vector",((unsigned char(*)(void*,void**,uint16_t))at(0xf0000001))(object+0x80,&reference,22));
        member("record_vector",((unsigned char(*)(void*,void**,uint16_t))at(0x4187300))(object+0x98,&reference,22));
        member("team_links",((unsigned char(*)(void*,void**))at(0x2153f30))(object+0x28,&reference));
        if(stream.cursor+1>stream.size)desktop_finish_and_exit(197);stream.cursor++;
        unsigned result[8]={},result_count=0;
        ((void*(*)(void*,void**,void*,void*))at(0x32dffe0))(result,&reference,object+0x10,&result_count);
        member("setpiece_vector",result[0]==0);
        auto word=[&](){if(stream.cursor+4>stream.size)desktop_finish_and_exit(197);auto v=*(uint32_t*)(bytes.data()+stream.cursor);stream.cursor+=4;return v;};
        auto n=word();if(n>65536||stream.cursor+8ULL*n>stream.size)desktop_finish_and_exit(197);stream.cursor+=8ULL*n;
        n=word();if(n>65536||stream.cursor+5ULL*n>stream.size)desktop_finish_and_exit(197);stream.cursor+=5ULL*n;
        member("manager_end",true);
    }
    auto table_offset=stream.cursor;
    if(stream.cursor+2>stream.size)desktop_finish_and_exit(197);
    auto compact_count=*(uint16_t*)(bytes.data()+stream.cursor);stream.cursor+=2;
    for(unsigned i=0;i<compact_count;i++){
        if(stream.cursor+243>stream.size)desktop_finish_and_exit(197);auto row=bytes.data()+stream.cursor;
        if(*(uint32_t*)row!=10||row[4]||row[9]||row[14]!=3||row[50]!=3)desktop_finish_and_exit(197);
        for(unsigned p:{14u,50u})for(unsigned j=0;j<11;j++)if(row[p+3+j*3]!=5)desktop_finish_and_exit(197);
        stream.cursor+=243;
    }
    fprintf(log_file,"{\"event\":\"ai_table_boundary\",\"offset\":%llu,\"count\":%u,\"end\":%llu}\n",(unsigned long long)table_offset,compact_count,(unsigned long long)stream.cursor);fflush(log_file);
    if(stream.cursor+2>stream.size)desktop_finish_and_exit(197);
    auto presets=*(uint16_t*)(bytes.data()+stream.cursor);stream.cursor+=2;if(presets>512)desktop_finish_and_exit(197);
    auto team=*(unsigned char**)(match+0x15380);auto manager=*(unsigned char**)(team+0x630);
    for(unsigned i=0;i<presets;i++){
        auto start=stream.cursor;
        if(!((unsigned char(*)(void*,void**,unsigned char))at(0x161d20))(manager+0x1818,&reference,0)||stream.error)desktop_finish_and_exit(197);
        fprintf(log_file,"{\"event\":\"ai_preset_read\",\"index\":%u,\"offset\":%llu,\"end\":%llu}\n",i,(unsigned long long)start,(unsigned long long)stream.cursor);fflush(log_file);
    }
    if(stream.cursor+2>stream.size||*(uint16_t*)(bytes.data()+stream.cursor)!=0)desktop_finish_and_exit(197);stream.cursor+=2;
    if(stream.cursor!=stream.size||stream.error)desktop_finish_and_exit(197);
    fprintf(log_file,"{\"event\":\"ai_section_complete\",\"offset\":%llu,\"size\":%llu,\"presets\":%u,\"remaining\":0}\n",(unsigned long long)stream.cursor,(unsigned long long)stream.size,presets);fflush(log_file);desktop_finish_and_exit(0);
}
