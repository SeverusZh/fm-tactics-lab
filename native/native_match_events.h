// Observe native event packets immediately before the engine clears its queue.
// Hardware execution breakpoints leave the original code bytes unchanged.
#include <array>
#include <vector>
static unsigned char* desktop_event_match=nullptr;
static HANDLE desktop_event_thread=nullptr,desktop_event_ready=nullptr;
static bool desktop_event_audit=false;
static unsigned desktop_event_breaks=0;
static bool desktop_event_installed=false,desktop_event_restored=false;
static PVOID desktop_event_handler=nullptr;
static CONTEXT desktop_event_previous={};
static uint64_t desktop_event_seen[2048]={};static unsigned desktop_event_seen_count=0;
static unsigned desktop_event_nonzero_padding=0;
static bool desktop_event_details_disabled=false;
static void desktop_event_person(unsigned char* match,unsigned side,unsigned index){
    if(side>1){fputs("null",log_file);return;}auto team=*(unsigned char**)(match+0x15380+8*side);if(index>=team[0x72d]){fputs("null",log_file);return;}auto actor=*(unsigned char**)(team+0x138+8*index);if(!actor){fputs("null",log_file);return;}
    fprintf(log_file,"{\"side\":%u,\"roster_index\":%u,\"native_id\":%u,\"ip_position\":%u,\"oop_position\":%u}",side,index,*(unsigned*)(actor+0x50),*(unsigned*)(actor+0xce0),*(unsigned*)(actor+0xdb8));
}
static void desktop_capture_event_queue(unsigned char* match){
    if(desktop_event_details_disabled)return;
    int count=*(int*)(match+0x13e40);if(count<1||count>192)return;
    for(int i=0;i<count;i++){
        auto packet=match+0x12f40+i*20;unsigned kind=packet[0];
        if(packet[1]||packet[2]||packet[3])desktop_event_nonzero_padding++;
        if(kind>0x50)continue;
        if(kind==32||kind==26||kind==29){uint64_t hash=1469598103934665603ULL^(uint64_t)*(unsigned*)(match+0x154ec);unsigned length=kind==32?14:kind==26?12:8;for(unsigned j=0;j<length;j++)hash=(hash^packet[j])*1099511628211ULL;bool seen=false;for(unsigned j=0;j<desktop_event_seen_count;j++)if(desktop_event_seen[j]==hash)seen=true;if(seen)continue;if(desktop_event_seen_count<2048)desktop_event_seen[desktop_event_seen_count++]=hash;}
        if(kind==32){fprintf(log_file,"{\"event\":\"native_goal_event\",\"tick\":%d,\"clock\":%d,\"period\":%u,\"scoring_side\":%u,\"native_flags\":%u,\"scorer\":",*(int*)(match+0x154ec),*(int*)(match+0x15464),match[0x1556a],packet[12],packet[13]);desktop_event_person(match,packet[4],packet[5]);fputs(",\"assist\":",log_file);desktop_event_person(match,packet[6],packet[7]);fputs("}\n",log_file);}
        if(kind==26||kind==29){const char* card=kind==26?((packet[11]&1)?"second_yellow":"yellow"):"red";fprintf(log_file,"{\"event\":\"native_card_event\",\"tick\":%d,\"clock\":%d,\"period\":%u,\"event_tick\":%d,\"native_packet_kind\":%u,\"card\":\"%s\",\"player\":",*(int*)(match+0x154ec),*(int*)(match+0x15464),match[0x1556a],*(int*)(match+0x154ec),kind,card);desktop_event_person(match,packet[4],packet[5]);fputs("}\n",log_file);}

        if(desktop_event_audit){fprintf(log_file,"{\"event\":\"desktop_event_packet\",\"kind\":%u,\"tick\":%d,\"clock\":%d,\"period\":%u,\"hex\":\"",kind,*(int*)(match+0x154ec),*(int*)(match+0x15464),match[0x1556a]);for(unsigned j=0;j<20;j++)fprintf(log_file,"%02x",packet[j]);fputs("\"}\n",log_file);}
    }
}
static bool desktop_event_read(uintptr_t address,void* destination,size_t size){
    SIZE_T got=0;return address&&ReadProcessMemory(GetCurrentProcess(),(const void*)address,destination,size,&got)&&got==size;
}
static void desktop_final_incidents(unsigned char* match){
    uintptr_t context=0,bounds[2]={};const char* error=nullptr;
    if(!desktop_event_read((uintptr_t)match+0x14ea0,&context,sizeof(context))||
       !desktop_event_read(context+0x40,bounds,sizeof(bounds)))error="registry_header_unreadable";
    if(!error&&(bounds[1]<bounds[0]||bounds[1]-bounds[0]>32768||(bounds[1]-bounds[0])%sizeof(uintptr_t)))error="registry_bounds_invalid";
    std::vector<uintptr_t> pointers;std::vector<std::array<unsigned char,0x28>> records;
    if(!error){
        pointers.resize((bounds[1]-bounds[0])/sizeof(uintptr_t));records.resize(pointers.size());
        if(!pointers.empty()&&!desktop_event_read(bounds[0],pointers.data(),pointers.size()*sizeof(uintptr_t)))error="registry_index_unreadable";
        for(size_t i=0;!error&&i<pointers.size();i++)if(!desktop_event_read(pointers[i],records[i].data(),records[i].size()))error="registry_record_unreadable";
    }
    if(error){fprintf(log_file,"{\"event\":\"native_final_incident_registry\",\"valid\":false,\"error\":\"%s\",\"incidents\":[]}\n",error);return;}
    fputs("{\"event\":\"native_final_incident_registry\",\"schema\":1,\"valid\":true,\"incidents\":[",log_file);
    for(size_t i=0;i<records.size();i++){
        auto p=records[i].data();uint32_t tick=0;memcpy(&tick,p+0x18,sizeof(tick));
        fprintf(log_file,"%s{\"index\":%zu,\"native_type\":%u,\"side\":%u,\"roster_index\":%u,\"other_side\":%u,\"other_index\":%u,\"nominal_minute\":%u,\"added_minute\":%u,\"native_tick\":%u,\"person\":",i?",":"",i,p[0x1f],p[0x1d],p[0x1e],p[0x21],p[0x22],p[0x1c],p[0x20],tick);
        desktop_event_person(match,p[0x1d],p[0x1e]);fputs(",\"other_person\":",log_file);desktop_event_person(match,p[0x21],p[0x22]);
        fputs(",\"raw\":\"",log_file);for(auto value:records[i])fprintf(log_file,"%02x",value);fputs("\"}",log_file);
    }
    fputs("]}\n",log_file);
}
static void desktop_player_totals(unsigned char* match){
    if(desktop_event_details_disabled)return;
    desktop_final_incidents(match);
    fputs("{\"event\":\"native_player_match_totals\",\"players\":[",log_file);bool comma=false;
    // 72d is the actor pool; 72e is the registered match roster.
    // 127990/127b70 own the canonical statistics vector. Unused bench actors
    // may retain an incidental runtime pointer after fc330 rearranges players;
    // that pointer is not an additional player's statistics record.
    unsigned checked_records=0;bool identity_ok=true;
    for(unsigned side=0;side<2;side++){
        auto team=*(unsigned char**)(match+0x15380+8*side);
        auto context=*(unsigned char**)(match+0x14ea0),totals=*(unsigned char**)(context+0x70+8*side);
        auto begin=*(unsigned char***)(totals+0x250),end=*(unsigned char***)(totals+0x258);
        if(end<begin||end-begin<11||end-begin>26||end-begin!=team[0x72e]){identity_ok=false;continue;}
        for(auto item=begin;item!=end;item++){
            auto stats=*item;unsigned char* actor=nullptr;unsigned index=0,matches=0;
            for(unsigned i=0;i<team[0x72d];i++){
                auto candidate=*(unsigned char**)(team+0x138+8*i);
                if(person_key(candidate)==*(uint32_t*)(stats+0x18)){actor=candidate;index=i;matches++;}
            }
            if(matches!=1){identity_ok=false;continue;}checked_records++;
            fprintf(log_file,"%s{\"side\":%u,\"roster_index\":%u,\"native_id\":%u,\"goals\":%u,\"yellow_cards\":%u,\"red_cards\":%u,\"ip_position\":%u,\"oop_position\":%u}",comma?",":"",side,index,*(unsigned*)(actor+0x50),stats[0x8b],stats[0xa6],stats[0xa7],*(unsigned*)(actor+0xce0),*(unsigned*)(actor+0xdb8));comma=true;
        }
    }
    fprintf(log_file,"],\"queue_observations\":%u,\"observer_installed\":%s,\"nonzero_packet_padding_observations\":%u}\n",desktop_event_breaks,desktop_event_installed?"true":"false",desktop_event_nonzero_padding);fflush(log_file);
    fprintf(log_file,"{\"event\":\"native_player_statistics_identity_verified\",\"verified\":%s,\"canonical_records\":%u}\n",identity_ok?"true":"false",checked_records);fflush(log_file);
}
static LONG CALLBACK desktop_event_exception(EXCEPTION_POINTERS* e){
    if(e->ExceptionRecord->ExceptionCode!=EXCEPTION_SINGLE_STEP)return EXCEPTION_CONTINUE_SEARCH;
    auto c=e->ContextRecord;uintptr_t pc=c->Rip-(uintptr_t)native_base;
    if((pc!=0x4520d2e&&pc!=0x4520f05&&pc!=0x4520f4c&&pc!=0x1866c1&&pc!=0x8375c&&pc!=0x49870d0)||!(c->Dr6&7))return EXCEPTION_CONTINUE_SEARCH;
    c->Dr6=0;c->EFlags|=0x10000;desktop_event_breaks++;if(((pc==0x8375c)&&*(unsigned char**)(c->Rsi+0x280)==desktop_event_match)||((pc==0x49870d0)&&(unsigned char*)c->Rcx-0x12f40==desktop_event_match)||((pc!=0x8375c&&pc!=0x49870d0)&&(unsigned char*)c->Rdi==desktop_event_match))desktop_capture_event_queue(desktop_event_match);return EXCEPTION_CONTINUE_EXECUTION;
}
static DWORD WINAPI desktop_event_setup_thread(void*){
    CONTEXT c={};c.ContextFlags=CONTEXT_DEBUG_REGISTERS;SuspendThread(desktop_event_thread);
    if(GetThreadContext(desktop_event_thread,&c)&&!(c.Dr7&255)){desktop_event_previous=c;c.Dr0=(uintptr_t)at(desktop_event_audit?0x4520d2e:0x1866c1);c.Dr1=(uintptr_t)at(desktop_event_audit?0x4520f05:0x8375c);c.Dr2=(uintptr_t)at(desktop_event_audit?0x4520f4c:0x49870d0);c.Dr6=0;c.Dr7=(c.Dr7&~0xffff00ffULL)|0x15;desktop_event_installed=SetThreadContext(desktop_event_thread,&c)!=0;}
    ResumeThread(desktop_event_thread);SetEvent(desktop_event_ready);return 0;
}

static bool desktop_events_start(unsigned char* match){
    desktop_event_match=match;desktop_event_seen_count=desktop_event_breaks=desktop_event_nonzero_padding=0;desktop_event_installed=false;
    desktop_event_details_disabled=GetEnvironmentVariableW(L"FM27_SKIP_EVENT_DETAILS",nullptr,0)!=0;
    if(desktop_event_details_disabled){fputs("{\"event\":\"native_event_details_disabled\",\"observer_installed\":false}\n",log_file);fflush(log_file);return true;}
    desktop_event_audit=GetEnvironmentVariableW(L"FM27_DESKTOP_EVENTS_AUDIT",nullptr,0)!=0;
    desktop_event_thread=OpenThread(THREAD_GET_CONTEXT|THREAD_SET_CONTEXT|THREAD_SUSPEND_RESUME,FALSE,GetCurrentThreadId());
    desktop_event_ready=CreateEventW(nullptr,TRUE,FALSE,nullptr);desktop_event_handler=AddVectoredExceptionHandler(1,desktop_event_exception);
    if(!desktop_event_thread||!desktop_event_ready||!desktop_event_handler)return false;
    auto thread=CreateThread(nullptr,0,desktop_event_setup_thread,nullptr,0,nullptr);if(!thread)return false;
    DWORD waited=WaitForSingleObject(desktop_event_ready,10000);WaitForSingleObject(thread,10000);CloseHandle(thread);
    return waited==WAIT_OBJECT_0&&desktop_event_installed;
}
static DWORD WINAPI desktop_event_restore_thread(void*){
    CONTEXT c={};c.ContextFlags=CONTEXT_DEBUG_REGISTERS;
    if(SuspendThread(desktop_event_thread)!=DWORD(-1)){
        if(GetThreadContext(desktop_event_thread,&c)){
            c.Dr0=desktop_event_previous.Dr0;c.Dr1=desktop_event_previous.Dr1;c.Dr2=desktop_event_previous.Dr2;c.Dr3=desktop_event_previous.Dr3;
            c.Dr6=desktop_event_previous.Dr6;c.Dr7=desktop_event_previous.Dr7;
            desktop_event_restored=SetThreadContext(desktop_event_thread,&c)!=0;
        }
        ResumeThread(desktop_event_thread);
    }
    SetEvent(desktop_event_ready);return 0;
}
static bool desktop_events_stop(){
    if(desktop_event_details_disabled){desktop_event_details_disabled=false;desktop_event_match=nullptr;fputs("{\"event\":\"native_event_observer_stopped\",\"details_disabled\":true,\"debug_registers_untouched\":true}\n",log_file);fflush(log_file);return true;}
    desktop_event_restored=false;ResetEvent(desktop_event_ready);
    auto thread=CreateThread(nullptr,0,desktop_event_restore_thread,nullptr,0,nullptr);if(!thread)return false;
    DWORD waited=WaitForSingleObject(desktop_event_ready,10000);WaitForSingleObject(thread,10000);CloseHandle(thread);
    if(waited!=WAIT_OBJECT_0||!desktop_event_restored)return false;
    if(!RemoveVectoredExceptionHandler(desktop_event_handler))return false;
    desktop_event_handler=nullptr;CloseHandle(desktop_event_thread);CloseHandle(desktop_event_ready);
    desktop_event_thread=desktop_event_ready=nullptr;desktop_event_match=nullptr;desktop_event_installed=false;
    fputs("{\"event\":\"native_event_observer_stopped\",\"debug_registers_restored\":true}\n",log_file);fflush(log_file);return true;
}
