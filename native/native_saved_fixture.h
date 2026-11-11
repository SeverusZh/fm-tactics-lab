// Build 2493426, schema 7. Read only; unknown enclosing grammar is a hard stop.
static void saved_section_probe(void* interface_object){
    wchar_t path[32768]={};
    if(!GetEnvironmentVariableW(L"FM27_SAVE_SECTION_PROBE",path,32768))return;
    std::ifstream file(path,std::ios::binary|std::ios::ate);
    auto size=file.tellg();if(size<12||size>16*1024*1024)desktop_finish_and_exit(196);
    file.seekg(0);std::vector<unsigned char> bytes((size_t)size);if(!file.read((char*)bytes.data(),size))desktop_finish_and_exit(196);
    void* methods[8]={};methods[2]=(void*)desktop_tac_tell;methods[3]=(void*)desktop_tac_seek;methods[5]=(void*)desktop_tac_read;
    DesktopTacticStream stream={methods,0x200000001ULL,0,0,bytes.data(),bytes.size(),0};void* reference=&stream;
    auto need=[&](size_t n){if(n>stream.size||stream.cursor>stream.size-n){fprintf(log_file,"{\"event\":\"section_error\",\"offset\":%llu,\"error\":\"bounds\"}\n",(unsigned long long)stream.cursor);fflush(log_file);desktop_finish_and_exit(196);}};
    auto byte=[&](){need(1);return bytes[stream.cursor++];};
    auto u16=[&](){need(2);auto value=*(uint16_t*)(bytes.data()+stream.cursor);stream.cursor+=2;return value;};
    auto u32=[&](){need(4);auto value=*(uint32_t*)(bytes.data()+stream.cursor);stream.cursor+=4;return value;};
    auto fail=[&](const char* reason){fprintf(log_file,"{\"event\":\"section_error\",\"offset\":%llu,\"error\":\"%s\"}\n",(unsigned long long)stream.cursor,reason);fflush(log_file);desktop_finish_and_exit(196);};
    if(bytes.size()<12||memcmp(bytes.data(),"\x03\x01tad.\x07\0",8))fail("section header");
    *(unsigned char*)at(0x58204dc)=1;
    *(void**)at(0x581ca40)=at(0xe16120);*(void**)at(0x581ca48)=at(0xe16260);
    stream.cursor=8;unsigned count=u32();if(count>4096)fail("count");
    fprintf(log_file,"{\"event\":\"section_count\",\"count\":%u}\n",count);fflush(log_file);
    auto print_plan=[&](unsigned char* plan){
        if(!plan){fputs("null",log_file);return;}
        fprintf(log_file,"{\"mentality\":%u,\"team_bits\":\"",plan[0x105]);for(unsigned j=0;j<16;j++)fprintf(log_file,"%02x",plan[0xe0+j]);fputs("\",\"mapping\":[",log_file);
        for(unsigned j=0;j<11;j++)fprintf(log_file,"%s%u",j?",":"",plan[0x79c+j]);fputs("],\"phases\":[",log_file);
        for(unsigned ph=0;ph<2;ph++){if(ph)fputc(',',log_file);fputc('[',log_file);for(unsigned j=0;j<11;j++){
            auto cell=plan+(ph?0x438:0x118)+j*0x48;auto pi=instruction_entry(cell,false);
            fprintf(log_file,"%s{\"position\":%u,\"role_flags\":\"%llu\",\"pi_flags\":\"%llu\",\"target_player\":%u,\"target_position\":%u}",j?",":"",*(unsigned*)cell,(unsigned long long)*(uint64_t*)(cell+64),pi?(unsigned long long)pi[1]:0,pi?((unsigned char*)pi)[20]:255,pi?*(unsigned*)((unsigned char*)pi+16):0);
        }fputc(']',log_file);}fputs("]}",log_file);
    };
    for(unsigned group=0;group<2;group++){
    if(group){if(byte()!=0)fail("active fixture chain present");count=u32();if(count>4096)fail("history count");fprintf(log_file,"{\"event\":\"section_history_count\",\"count\":%u}\n",count);fflush(log_file);}
    for(unsigned index=0;index<count;index++){
        auto start=stream.cursor;auto type=byte();if(type>1)fail("fixture type");
        if(byte()!=1||byte()!=0||byte()!=31)fail("fixture basic variant");
        // Original revision-31 basic-field order. Keep references as identities;
        // no fabricated database objects are supplied to an original reader.
        auto stage=u32(),stadium=u32();u16();
        if(byte()!=0)fail("home reference variant");auto home=u32();byte();byte();
        if(byte()!=0)fail("away reference variant");auto away=u32();byte();byte();
        auto date=u32();u32();byte();u16();u32();u32();
        byte();byte();byte();byte();u16();for(unsigned j=0;j<5;j++)byte();u16();byte();byte();byte();byte();
        unsigned core_present=byte();if(core_present>1)fail("core presence");
        unsigned char* core=nullptr;
        if(core_present){
            core=((unsigned char*(*)())at(0x4ba8840))();
            auto okay=((unsigned char(*)(void*,void**,void*,void*))at(0x26329a0))(core,&reference,interface_object,nullptr);
            if(!okay||stream.error)fail("original core reader rejected");
        }
        need(22);stream.cursor+=22; // Native 4973d40's four u32s, date, two flags.
        auto composite_start=stream.cursor;unsigned char* plans[8]={};bool composite=false;
        if(type==0){
            auto present=byte();if(present>1)fail("composite presence");
            if(present){composite=true;composite_start=stream.cursor;
                if(!((unsigned char(*)(void*,void**))at(0x3919b10))(plans,&reference)||stream.error)fail("original composite reader rejected");}
            byte();
        }else{
            if(u16()!=0)fail("full fixture detail entries unsupported");
            if(byte()!=0)fail("embedded native recording present");
            if(byte()!=0||byte()!=0||byte()!=0)fail("legacy full detail present");
            u32();byte();byte();
        }
        fprintf(log_file,"{\"event\":\"saved_fixture_walked\",\"group\":%u,\"index\":%u,\"offset\":%llu,\"end\":%llu,\"type\":%u,\"stage\":%u,\"home_team_id\":%u,\"away_team_id\":%u,\"date_word\":%u,\"composite_offset\":%llu,\"rosters\":[",group,index,(unsigned long long)start,(unsigned long long)stream.cursor,type,stage,home,away,date,(unsigned long long)composite_start);
        for(unsigned side=0;side<2;side++){
            if(side)fputc(',',log_file);fputc('[',log_file);
            if(core){auto team=*(unsigned char**)(core+0x70+8*side);auto first=*(unsigned char***)(team+0x250),last=*(unsigned char***)(team+0x258);if(last-first>26||last<first)fail("player stats count");for(auto p=first;p<last;p++)fprintf(log_file,"%s%u",p==first?"":",",*(unsigned*)(*p+0x18));}
            fputc(']',log_file);
        }
        fputs("],\"plans\":[",log_file);
        print_plan(plans[0]);fputc(',',log_file);print_plan(plans[1]);fputs("]}\n",log_file);fflush(log_file);
    }
    }
    if(stream.error||stream.cursor!=stream.size)fail("trailing or unread bytes");
    fprintf(log_file,"{\"event\":\"section_walk_end\",\"offset\":%llu,\"remaining\":0,\"simulation_ticks_executed\":0}\n",(unsigned long long)stream.cursor);fflush(log_file);desktop_finish_and_exit(0);
}
