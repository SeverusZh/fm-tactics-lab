// Desktop-only read-only diagnostic snapshots. Raw values are not UI metrics
// until the original writers/getters have established their meaning.
static void desktop_initial_state_snapshot(unsigned char* match){
    bool controlled=false;for(auto e:scenario_edits)if(e.kind==15&&e.b==22)controlled=true;
    if(!controlled)return;
    fputs("{\"event\":\"native_controlled_initial_state\",\"players\":[",log_file);
    unsigned n=0;
    for(unsigned side=0;side<2;side++){
        auto team=*(unsigned char**)(match+0x15380+side*8);
        for(unsigned i=0;i<team[0x72d];i++){
            auto p=*(unsigned char**)(team+0x138+i*8);
            fprintf(log_file,"%s{\"side\":%u,\"roster_index\":%u,\"id\":%u,\"condition\":%u,\"sharpness\":%u,\"sharpness_secondary\":%u,\"fatigue_raw\":%u,\"team_cohesion\":%u,\"club_cohesion\":%u,\"morale\":%u,\"runtime_morale\":%u}",n++?",":"",side,i,*(unsigned*)(p+0x50),*(unsigned short*)(p+0xc8a),*(unsigned short*)(p+0xc90),*(unsigned short*)(p+0xc7a),*(unsigned short*)(p+0xc84),p[0xca8],p[0xca2],p[0xca3],p[0x1e2c]);
        }
    }
    fputs("]}\n",log_file);fflush(log_file);
}
static unsigned char* desktop_watched_stats=nullptr;
static unsigned char* desktop_watched_match=nullptr;
static HANDLE desktop_watch_thread=nullptr,desktop_watch_ready=nullptr;
static unsigned desktop_watch_offsets[]={0x60,0x80,0x84,0xa4};
static uint64_t desktop_watch_seen[128]={};static unsigned desktop_watch_count=0;
static const char* desktop_native_type(void* object){
    if(!object)return "null";auto table=*(uintptr_t**)object;if((uintptr_t)table<(uintptr_t)native_base||(uintptr_t)table>(uintptr_t)native_base+0x1821c000)return "unknown";auto col=table[-1];auto descriptor=*(unsigned*)(col+12);return(char*)native_base+descriptor+16;
}
static LONG CALLBACK desktop_stats_exception(EXCEPTION_POINTERS* e){
    if(e->ExceptionRecord->ExceptionCode!=EXCEPTION_SINGLE_STEP)return EXCEPTION_CONTINUE_SEARCH;
    auto c=e->ContextRecord;auto flags=c->Dr6&15;MEMORY_BASIC_INFORMATION region={};VirtualQuery((void*)c->Rip,&region,sizeof(region));if(!flags||region.AllocationBase!=native_base)return EXCEPTION_CONTINUE_SEARCH;
    c->Dr6=0;c->EFlags|=0x10000;
    for(unsigned slot=0;slot<4;slot++)if(flags&(1u<<slot)){
        uint64_t key=((c->Rip-(uintptr_t)native_base)<<3)|slot;bool seen=false;for(unsigned j=0;j<desktop_watch_count;j++)if(desktop_watch_seen[j]==key)seen=true;if(seen||desktop_watch_count>=128)continue;desktop_watch_seen[desktop_watch_count++]=key;
        fprintf(log_file,"{\"event\":\"desktop_stat_producer\",\"field\":%u,\"value\":%u,\"tick\":%d,\"rva\":\"%llx\",\"stack\":[",desktop_watch_offsets[slot],*(unsigned*)(desktop_watched_stats+desktop_watch_offsets[slot]),*(int*)(desktop_watched_match+0x154ec),(unsigned long long)(c->Rip-(uintptr_t)native_base));
        CONTEXT walk=*c;for(unsigned j=0;j<10&&walk.Rip;j++){
            fprintf(log_file,"%s\"%llx\"",j?",":"",(unsigned long long)(walk.Rip-(uintptr_t)native_base));DWORD64 image=0,frame=0;PVOID data=nullptr;auto entry=RtlLookupFunctionEntry(walk.Rip,&image,nullptr);auto old=walk.Rsp;
            if(entry)RtlVirtualUnwind(UNW_FLAG_NHANDLER,image,walk.Rip,entry,&walk,&data,&frame,nullptr);else{walk.Rip=*(DWORD64*)walk.Rsp;walk.Rsp+=8;}if(walk.Rsp<=old||walk.Rsp-old>0x100000||walk.Rip<(uintptr_t)native_base||walk.Rip>=(uintptr_t)native_base+0x1821c000)break;
        }fputs("]",log_file);if(slot==0&&c->Rip-(uintptr_t)native_base==0x51a90)fprintf(log_file,",\"record_type\":\"%s\",\"record_value\":%.9g",desktop_native_type((void*)c->R14),*(float*)(c->R14+0x30));fputs("}\n",log_file);fflush(log_file);
    }return EXCEPTION_CONTINUE_EXECUTION;
}
static void desktop_match_statistics(unsigned char* match){
    unsigned char* records[2]={};unsigned ticks[2]={};for(unsigned side=0;side<2;side++){records[side]=*(unsigned char**)(*(unsigned char**)(match+0x15380+side*8)+0x690);ticks[side]=*(unsigned*)(records[side]+0x7c);}
    unsigned total=ticks[0]+ticks[1];fprintf(log_file,"{\"event\":\"native_match_statistics\",\"schema\":1,\"source\":\"original_team_statistics\",\"teams\":[");
    for(unsigned side=0;side<2;side++){
        auto stats=records[side];fprintf(log_file,"%s{\"side\":%u,\"possession_ticks\":%u,\"possession\":",side?",":"",side,ticks[side]);if(total)fprintf(log_file,"%.9g",(double)ticks[side]/total);else fputs("null",log_file);
        fprintf(log_file,",\"xg\":%.9g,\"shots\":%u,\"shots_on_target\":%u,\"passes\":%u,\"completed_passes\":%u}",*(float*)(stats+0x60),stats[0x16f],stats[0x170],*(unsigned short*)(stats+0xd8),*(unsigned short*)(stats+0xda));
    }fputs("]}\n",log_file);fflush(log_file);
}
static DWORD WINAPI desktop_watch_setup(void*){
    CONTEXT c={};c.ContextFlags=CONTEXT_DEBUG_REGISTERS;SuspendThread(desktop_watch_thread);
    if(GetThreadContext(desktop_watch_thread,&c)&&!(c.Dr7&255)){c.Dr0=(uintptr_t)desktop_watched_stats+0x60;c.Dr1=(uintptr_t)desktop_watched_stats+0x80;c.Dr2=(uintptr_t)desktop_watched_stats+0x84;c.Dr3=(uintptr_t)desktop_watched_stats+0xa4;c.Dr6=0;c.Dr7=(c.Dr7&~0xffff00ffULL)|0xdddd0055ULL;SetThreadContext(desktop_watch_thread,&c);}
    ResumeThread(desktop_watch_thread);SetEvent(desktop_watch_ready);return 0;
}
static void desktop_stats_snapshot(unsigned char* match,const char* stage){
    bool watch=GetEnvironmentVariableW(L"FM27_DESKTOP_STATS_AUDIT",nullptr,0)!=0;
    if(!watch&&!GetEnvironmentVariableW(L"FM27_DESKTOP_EVENTS_AUDIT",nullptr,0))return;
    if(watch&&!strcmp(stage,"prepared")){
        desktop_watched_match=match;desktop_watched_stats=*(unsigned char**)(*(unsigned char**)(match+0x15380)+0x690);desktop_watch_thread=OpenThread(THREAD_GET_CONTEXT|THREAD_SET_CONTEXT|THREAD_SUSPEND_RESUME,FALSE,GetCurrentThreadId());desktop_watch_ready=CreateEventW(nullptr,TRUE,FALSE,nullptr);AddVectoredExceptionHandler(1,desktop_stats_exception);auto worker=CreateThread(nullptr,0,desktop_watch_setup,nullptr,0,nullptr);WaitForSingleObject(desktop_watch_ready,10000);CloseHandle(worker);
    }
    for(unsigned s=0;s<2;s++){
        auto team=*(unsigned char**)(match+0x15380+s*8);auto stats=*(unsigned char**)(team+0x690);
        fprintf(log_file,"{\"event\":\"desktop_stats_snapshot\",\"stage\":\"%s\",\"side\":%u,\"team_hex\":\"",stage,s);
        for(unsigned j=0;j<0x200;j++)fprintf(log_file,"%02x",stats[j]);fputs("\",\"players\":[",log_file);
        for(unsigned i=0;i<team[0x72d];i++){
            auto actor=*(unsigned char**)(team+0x138+i*8);auto record=*(unsigned char**)(actor+0x1880);
            fprintf(log_file,"%s{\"id\":%u,\"hex\":\"",i?",":"",*(unsigned*)(actor+0x50));
            if(record)for(unsigned j=0;j<0x100;j++)fprintf(log_file,"%02x",record[j]);fputs("\"}",log_file);
        }fputs("]}\n",log_file);
    }fflush(log_file);
}
