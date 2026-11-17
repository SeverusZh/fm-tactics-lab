#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <io.h>
#include <stdio.h>
#include <wchar.h>
#include <intrin.h>
#include <stdint.h>
#include <vector>
#include <fstream>
#include <algorithm>
#include <share.h>
#include <filesystem>
#include <string>
#include <bcrypt.h>
#include <mutex>
#include <map>
#include <array>
static std::recursive_mutex worker_log_lock;
#include "fm27_tactic_bindings.h"
#pragma comment(lib,"bcrypt.lib")

// Headless native match host. This intentionally retains the complete, unchanged
// licensed native library; it is NOT a physically reduced engine binary.
namespace fs=std::filesystem;
static fs::path bundle,fixture,output;
static fs::path desktop_game_root;
static fs::path dump_input;
static fs::path scenario_file;
static bool seed_override=false;
static bool inspect_fixture_only=false;
static uint32_t requested_seed=0;
static int tick_step=1;
static bool policy_audit=false;
static fs::path worker_manifest;static bool worker_bootstrapped=false;
static ULONGLONG timing_start=0,timing_loaded=0,timing_active=0,timing_prepare=0,timing_ready=0;
static FILE* log_file;
static unsigned char* native_base;
static uint64_t input_cursor=0,input_reads=0;
#include "native_steam_lifecycle.h"
static void* at(uintptr_t rva){
    if(rva>=0xf0000000){
        static const unsigned missing[]={0xfb2580,0x4a7c550};
        fprintf(log_file,"{\"event\":\"formal_unmapped_reference\",\"reference\":%u}\n",missing[rva-0xf0000000]);
        fflush(log_file);desktop_finish_and_exit(251);
    }
    return native_base+rva;
}
static int audit_policies(){
    std::vector<uint32_t> positions;
    for(auto row:fm27_role_positions)if(std::find(positions.begin(),positions.end(),row.position)==positions.end())positions.push_back(row.position);
    for(auto position:positions)for(unsigned phase=0;phase<2;phase++)for(unsigned cb=0;cb<=11;cb++)for(unsigned dm=0;dm<=11;dm++){
        auto mask=((uint64_t(*)(const uint32_t*,unsigned))at(phase?0xc3220:0x1711a50))(&position,cb);
        if(phase&&(position&128)&&dm==1)mask&=~0x20000ULL;
        fprintf(log_file,"{\"event\":\"role_policy\",\"phase\":%u,\"position\":%u,\"cb\":%u,\"dm\":%u,\"mask\":\"%llu\"}\n",phase,position,cb,dm,(unsigned long long)mask);
    }
    const uint64_t duties[]={0,2097152,4194304,8388608,33554432,67108864,17179869184};
    for(auto row:fm27_role_positions)for(auto duty:duties)for(uint32_t version:{0x1a080000u,0x1b000000u}){
        char statuses[44]={};statuses[0]='0';uint64_t editable=0;
        for(unsigned option=1;option<=42;option++){
            uint32_t status=0;auto ok=((unsigned char(*)(unsigned,const uint32_t*,uint64_t,const uint32_t*,uint32_t*))at(row.phase?0x27740:0x47ff410))(option,&row.position,row.role|duty,&version,&status);
            if(status>3)return 112;statuses[option]='0'+status;if(ok)editable|=1ULL<<option;
        }
        fprintf(log_file,"{\"event\":\"pi_policy\",\"phase\":%u,\"position\":%u,\"role\":\"%llu\",\"duty\":\"%llu\",\"version\":%u,\"statuses\":\"%s\",\"editable\":\"%llu\"}\n",row.phase,row.position,(unsigned long long)row.role,(unsigned long long)duty,version,statuses,(unsigned long long)editable);
    }
    fflush(log_file);return 0;
}
static constexpr uint32_t current_pi_policy_version=0x1b000000u;
static constexpr unsigned pi_policy_version_offsets[]={0xf0,0x430,0x750,0x798};
struct ScenarioEdit {uint32_t kind,side,a,b,value;};
static std::vector<ScenarioEdit> scenario_edits;
static std::vector<unsigned char> source_generation_config;
static ScenarioEdit current_scenario_edit={};
static const char* scenario_stage="initial";
static bool game_constraints[2]={false,false};
static unsigned char* original_roster[2][26]={};
static uint32_t person_key(unsigned char* player){
    void* interface_object=*(void**)at(0x581cab0);uint32_t key=0xffffffff;
    auto vtable=*(void***)interface_object;
    ((void(*)(void*,uint32_t*,void*))vtable[0x1f0/8])(interface_object,&key,player+0x28);return key;
}
static uint32_t packed_oi(const unsigned char* p){return p[0]|(p[1]<<8)|(p[2]<<16);}
static void set_oi(unsigned char* p,uint32_t value){p[0]=(unsigned char)value;p[1]=(unsigned char)(value>>8);p[2]=(unsigned char)(value>>16);}
static unsigned char* priority_list(unsigned char* manager,unsigned id){
    if(id==0)return manager+0x8b8;
    if(id==1)return manager+0x8d0;
    if(id>=12&&id<20)return manager+0x7e0+(id-12)*24;
    if(id>11)return nullptr;
    return ((unsigned char*(*)(void*,unsigned char,signed char))at(0x31c27d0))(manager+0x6f0,5+(id-2)/2,(id-2)%2);
}
static bool valid_oi(uint32_t v){return !(v&~0x83f3fu)&&(v&7)<=2&&((v>>3)&7)<=2&&((v>>8)&7)<=3&&((v>>11)&7)<=3;}
static unsigned char* routine_vector(unsigned char* manager,unsigned type){
    static const unsigned offsets[]={0xd10,0xd40,0xda0,0xdd0,0xd70,0xd28,0xd58,0xdb8,0xde8,0xd88};
    return type<10?manager+0x8f0+offsets[type]:nullptr;
}
static unsigned char* routine(unsigned char* manager,unsigned encoded){
    if(encoded/16>=10||encoded%16>=3)return nullptr;
    return ((unsigned char*(*)(void*,unsigned char,size_t))at(0x8da40))(manager+0x8f0,encoded/16,encoded%16);
}
static unsigned char* tactic_cell(unsigned char* manager,unsigned encoded,bool canonical=false){
    if(encoded/16>1||encoded%16>=11)return nullptr;
    return manager+(canonical?0x2768:0x1818)+(encoded/16?0x438:0x118)+(encoded%16)*0x48;
}
#include "formal_tactic_vector.h"
static uint64_t* instruction_entry(unsigned char* cell,bool create){
    uint64_t key=*(uint64_t*)(cell+0x40)&0xfffffffbf91fffffULL;
    auto p=*(uint64_t**)(cell+8),end=*(uint64_t**)(cell+16);
    while(p!=end&&*p<key)p+=3;
    if(p!=end&&*p==key)return p;
    if(!create)return nullptr;
    uint64_t value[3]={key,0,0xff00000000ULL};
    return formal_insert_tactic_instruction(cell,p,value);
}
static bool profile_value(unsigned char* player,unsigned field,uint32_t value,bool write,unsigned char* owner_team=nullptr){
    unsigned offset=0,size=0,max=0xffffffff,min=0;
    if(field==0){if(value<140||value>220)return false;float height=value/100.0f;uint32_t bits;memcpy(&bits,&height,4);if(write)memcpy(player+0x6c,&bits,4);return *(uint32_t*)(player+0x6c)==bits;}
    if(field==1){offset=0x79;size=1;min=14;max=60;}
    else if(field>=2&&field<=8){offset=0x72+field-2;size=1;min=1;max=20;}
    else if(field==9||field==10){offset=0xbb8+4*(field-9);size=4;}
    else if(field>=11&&field<=18){static const unsigned offsets[]={0xc98,0xc8c,0xc96,0xc78,0xc8a,0xc90,0xc7a,0xc84};offset=offsets[field-11];size=2;max=field==11?200:(field==18?65535:10000);}
    else if(field==19){offset=0x70;size=1;min=40;max=140;}
    else if(field==20||field==21){offset=field==20?0xca8:0xca2;size=1;max=100;}
    else if(field==22){offset=0xca3;size=1;min=1;max=20;}
    else return false;
    if(value<min||value>max)return false;
    if(write&&field==20){if(!owner_team)return false;int adjustment=(signed char)owner_team[0x121];int input=(int)value*2-50-adjustment*5;if(input<0||input>100||abs(input-(int)value)>25)return false;value=(uint32_t)input;}if(write)memcpy(player+offset,&value,size);
    uint32_t actual=0;memcpy(&actual,player+offset,size);if(!write&&actual!=value)fprintf(stderr,"profile mismatch field=%u expected=%u actual=%u\n",field,value,actual);return actual==value;
}
static void log_phase_players(unsigned char* team,unsigned phase){
    fputs("[",log_file);
    for(unsigned i=0;i<11;i++){
        auto actor=*(unsigned char**)(team+0x138+8*i);auto cell=actor+(phase?0xdb8:0xce0);auto pi=instruction_entry(cell,false);
        fprintf(log_file,"%s{\"slot\":%u,\"position\":%u,\"role\":\"%llu\",\"instruction_flags\":\"%llu\"}",i?",":"",i,*(uint32_t*)cell,(unsigned long long)*(uint64_t*)(cell+0x40),(unsigned long long)(pi?pi[1]:0));
    }
    fputs("]",log_file);
}
static bool apply_scenario(unsigned char* match,bool tactics_only=false){
    if(scenario_file.empty()){source_generation_config.clear();return true;}
    uint32_t count=(uint32_t)scenario_edits.size();
    if(!tactics_only){
        std::ifstream file(scenario_file,std::ios::binary);char magic[8]={};
        file.read(magic,8);file.read((char*)&count,4);
        bool source_config=!memcmp(magic,"FM27CFG2",8);
        if(!file||(!source_config&&memcmp(magic,"FM27CFG1",8))||count>20000)return false;
        scenario_edits.resize(count);file.read((char*)scenario_edits.data(),count*sizeof(ScenarioEdit));
        source_generation_config.clear();
        if(source_config){
            source_generation_config.resize(584);file.read((char*)source_generation_config.data(),584);
            if(memcmp(source_generation_config.data(),"FM27DUL1",8))return false;
        }
        if(!file||file.peek()!=EOF)return false;
        for(auto e:scenario_edits)if(e.kind==13){if(e.side>1||e.value>1)return false;game_constraints[e.side]=e.value!=0;}
    }
    unsigned char creator[2][0x28];bool changed[2]={false,false};
    for(unsigned side=0;side<2;side++){
        auto team=*(unsigned char**)(match+0x15380+8*side);auto manager=*(unsigned char**)(team+0x630);
        memcpy(creator[side],manager+0x18f8,0x28);
        for(unsigned i=0;i<26;i++)original_roster[side][i]=*(unsigned char**)(team+0x138+i*8);
    }
    unsigned attributes=0,instructions=0;
    for(const auto& edit:scenario_edits){
        current_scenario_edit=edit;scenario_stage="records";
        if(edit.side>1)return false;
        auto team=*(unsigned char**)(match+0x15380+8*edit.side);
        if(edit.kind==62){
            if(edit.side||edit.a||edit.b||edit.value!=current_pi_policy_version)return false;
            // Native preparation takes the plan versions from the match, not
            // from the old carrier's plan. Set the input plan for PI checks and export too.
            *(uint32_t*)(match+0xa3a)=edit.value;
            for(unsigned side=0;side<2;side++){
                auto manager=*(unsigned char**)(*(unsigned char**)(match+0x15380+8*side)+0x630);
                for(auto offset:pi_policy_version_offsets)*(uint32_t*)(manager+0x1818+offset)=edit.value;
            }
        }else if(edit.kind==61){
            if(edit.a>4||edit.b||edit.value>100)return false;
        }else if(edit.kind==17){
            if(edit.value<11||edit.value>team[0x72d])return false;
            // Apply eligibility after original preparation initializes all carrier slots.
        }else if(edit.kind==1){
            if(edit.a>=team[0x72d]||edit.b>=69||edit.value>(edit.b<15?20u:100u))return false;
            if(edit.b>=15&&!edit.value)return false;
            auto player=*(unsigned char**)(team+0x138+edit.a*8);
            if(!tactics_only)player[0x480+edit.b]=(unsigned char)edit.value;attributes++;
        }else if(edit.kind==18){
            auto manager=*(unsigned char**)(team+0x630);auto cell=tactic_cell(manager,edit.a);if(!cell)return false;
            auto entry=instruction_entry(cell,true);entry[1]=0;*(uint32_t*)((unsigned char*)entry+16)=0;((unsigned char*)entry)[20]=255;
        }else if(edit.kind==15){
            if(edit.a>=team[0x72d]||!profile_value(*(unsigned char**)(team+0x138+8*edit.a),edit.b,edit.value,!tactics_only,team))return false;
        }else if(edit.kind==2){
            const FM27TeamOption* selected=nullptr;
            for(const auto& option:fm27_team_options)if(option.group==edit.a&&option.value==edit.value)selected=&option;
            if(!selected)return false;
            unsigned bit=((unsigned(*)(unsigned))at(0x6687d0))(edit.value);
            if(bit!=selected->bit)return false;
            for(const auto& option:fm27_team_options)if(option.group==edit.a&&option.bit)creator[edit.side][option.bit/8]&=(unsigned char)~(1u<<(option.bit%8));
            if(bit)creator[edit.side][bit/8]|=(unsigned char)(1u<<(bit%8));
            changed[edit.side]=true;instructions++;
        }else if(edit.kind==47){
            auto manager=*(unsigned char**)(team+0x630);auto obj=routine(manager,edit.a);if(!obj||edit.value>255)return false;obj[0x15]=(unsigned char)edit.value;
        }else if(edit.kind==60){
            if(edit.a>=128||edit.value>1)return false;
            bool known=false;for(auto option:fm27_team_options)if(option.bit&&option.bit==edit.a)known=true;if(known)return false;
            creator[edit.side][edit.a/8]=(creator[edit.side][edit.a/8]&~(1u<<(edit.a%8)))|(edit.value<<(edit.a%8));changed[edit.side]=true;
        }else if(edit.kind==3){
            if(edit.value<1||edit.value>7)return false;
            creator[edit.side][0x25]=(unsigned char)edit.value;changed[edit.side]=true;
        }else if(edit.kind==4||edit.kind==5||edit.kind==6||edit.kind==7){
            auto manager=*(unsigned char**)(team+0x630);auto cell=tactic_cell(manager,edit.a);
            if(!cell)return false;
            if(edit.kind==4){
                uint64_t role=((uint64_t)edit.b<<32)|edit.value;bool valid=false;
                for(auto entry:fm27_roles)if(entry.phase==edit.a/16&&entry.value==role)valid=true;
                if(!valid)return false;
                // Preserve the serialized duty when editing an existing role.
                *(uint64_t*)(cell+0x40)=role|(*(uint64_t*)(cell+0x40)&~0xfffffffbf91fffffULL);
            }else if(edit.kind==5){
                bool valid=false;for(auto value:fm27_positions)if(value==edit.value)valid=true;
                if(!valid)return false;*(uint32_t*)cell=edit.value;
            }else if(edit.kind==6){
                bool valid=false;uint64_t mask=0;
                for(auto option:fm27_player_options)if(option.group==edit.b){
                    if(option.value==edit.value)valid=true;
                    if(option.value)mask|=1ULL<<option.value;
                }
                if(!valid)return false;
                if(game_constraints[edit.side]&&edit.value){
                    uint32_t status=0,position=*(uint32_t*)cell;auto version=(uint32_t*)(manager+0x1908);
                    auto policy=(unsigned char(*)(unsigned,uint32_t*,uint64_t,uint32_t*,uint32_t*))at(edit.a/16?0x27740:0x47ff410);
                    if(!policy(edit.value,&position,*(uint64_t*)(cell+0x40),version,&status)||status!=0)return false;
                }
                auto entry=instruction_entry(cell,true);if(!entry)return false;
                entry[1]=(entry[1]&~mask)|(edit.value?1ULL<<edit.value:0);
            }else{
                // Recorded PI payload: flags u64, position mask u32, player index u8.
                if(edit.b==0){if(edit.value!=255&&edit.value>=26)return false;}
                else if(edit.b==1){bool valid=edit.value==0;for(auto p:fm27_positions)if(p==edit.value)valid=true;if(!valid)return false;}
                else return false;
                auto entry=instruction_entry(cell,true);
                if(edit.b==0)((unsigned char*)entry)[20]=(unsigned char)edit.value;
                else *(uint32_t*)((unsigned char*)entry+16)=edit.value;
            }
        }else if(edit.kind==14){
            auto manager=*(unsigned char**)(team+0x630);auto cell=tactic_cell(manager,edit.a);if(!cell)return false;
            uint64_t duty=((uint64_t)edit.b<<32)|edit.value;
            if(duty!=0&&duty!=2097152&&duty!=4194304&&duty!=8388608&&duty!=33554432&&duty!=67108864&&duty!=17179869184ULL)return false;
            *(uint64_t*)(cell+0x40)=(*(uint64_t*)(cell+0x40)&0xfffffffbf91fffffULL)|duty;
        }else if(edit.kind==20||edit.kind==21){
            if(!valid_oi(edit.value))return false;auto manager=*(unsigned char**)(team+0x630);
            if(edit.kind==20){
                auto other=*(unsigned char**)(match+0x15380+8*(1-edit.side));if(edit.a>=other[0x72d])return false;
                set_oi(manager+0x16f8+edit.a*3,edit.value);
            }else{
                bool valid=false;for(auto p:fm27_positions)if(p==edit.a)valid=true;if(!valid)return false;
                auto row=((unsigned char*(*)(void*,uint32_t))at(0x32e4380))(manager+0x1748,edit.a);set_oi(row,edit.value);
            }
        }else if(edit.kind==30){
            auto manager=*(unsigned char**)(team+0x630);auto list=priority_list(manager,edit.a);if(!list)return false;
            if(edit.b==0xffffffff){*(void**)(list+8)=*(void**)list;}
            else{
                if(edit.value>=team[0x72d]||edit.b>=26)return false;
                uint32_t key=person_key(original_roster[edit.side][edit.value]);
                if((*(uint32_t**)(list+8)-*(uint32_t**)list)!=edit.b)return false;
                ((void(*)(void*,uint32_t,const uint32_t*,size_t))at(0x4bcffd0))(list,0xffffffff,&key,1);
            }
        }else if(edit.kind==46){
            if(edit.a>2||edit.value>1)return false;auto manager=*(unsigned char**)(team+0x630);manager[0x16f0+edit.a]=(unsigned char)edit.value;
        }else if(edit.kind==40){
            auto manager=*(unsigned char**)(team+0x630);auto vec=routine_vector(manager,edit.a);
            if(!vec||edit.value<1||edit.value>3)return false;
            auto begin=*(unsigned char***)vec,end=*(unsigned char***)(vec+8);if(begin==end)return false;
            while(size_t(end-begin)>edit.value){auto obj=*--end;((void(*)(void*,unsigned))(*(void***)obj)[0])(obj,1);*(void**)(vec+8)=end;}
            while(size_t(end-begin)<edit.value){
                auto src=begin[0];size_t size=(edit.a==5||edit.a==7)?0x158:(edit.a==2||edit.a==3||edit.a==6||edit.a==8)?0x150:0x148;
                auto obj=(unsigned char*)((void*(*)(void*,size_t))at(0xc03d0))(at(0x581bf30),size);memset(obj,0,size);*(void***)obj=*(void***)src;
                ((void*(*)(void*,void*))(*(void***)obj)[2])(obj,src);
                *(uint32_t*)(obj+0x10)=0x4e554c4c;
                ((void*(*)(void*,void*,const void*))at(0x4bb38e0))(vec,end,&obj);
                begin=*(unsigned char***)vec;end=*(unsigned char***)(vec+8);
            }
        }else if(edit.kind>=41&&edit.kind<=45){
            auto manager=*(unsigned char**)(team+0x630);auto obj=routine(manager,edit.a);if(!obj)return false;auto vt=*(void***)obj;
            if(edit.kind==41){
                if(edit.b==0){if(edit.value>2)return false;obj[0x14]=(unsigned char)edit.value;}
                else if(edit.b==1||edit.b==2){
                    auto current=((unsigned char(*)(void*))vt[18+edit.b-1])(obj);
                    unsigned kind=edit.a/16;
                    bool recorded_strategy=edit.b==1&&((edit.value==3&&(kind==5||kind==7||kind==8))||
                        (edit.value==4&&(kind==7||kind==8))||(kind==7&&edit.value==6));
                    if(current==255||(edit.value>(edit.b==2?1u:2u)&&!recorded_strategy))return false;
                    ((void(*)(void*,unsigned char))vt[20+edit.b-1])(obj,(unsigned char)edit.value);
                }else return false;
            }else if(edit.kind==42){
                if(edit.b)return false;
                for(unsigned g=0;g<8;g++){auto entry=obj+0x18+g*0x20;*(void**)(entry+16)=*(void**)(entry+8);}
                *(void**)(obj+0x120)=*(void**)(obj+0x118);*(void**)(obj+0x138)=*(void**)(obj+0x130);
            }else if(edit.kind==43){
                if(edit.b>=8||edit.value>=16||!(((unsigned char(*)(unsigned char,unsigned char))at(0x4bd12c0))(edit.b,edit.value)))return false;
                ((void(*)(void*,unsigned,char,char,char))at(0x87b80))(obj,edit.b,(char)edit.value,-1,0);
            }else if(edit.kind==44){
                if(edit.value>=8||edit.b>=4)return false;auto start=*(unsigned char**)(obj+0x118),end=*(unsigned char**)(obj+0x120);
                if(size_t(end-start)!=edit.b)return false;unsigned char value=(unsigned char)edit.value;
                ((void*(*)(void*,void*,const void*))at(0x8b530))(obj+0x118,end,&value);
            }else{
                unsigned g=edit.b/32,index=edit.b%32;if(g>=8||index>=10||edit.value>=16)return false;
                auto backup=*(unsigned char**)(obj+0x130),end=*(unsigned char**)(obj+0x138);bool found=false;
                for(auto p=backup;p<end;p+=3)if(p[0]==g&&p[1]==index){found=true;break;}
                if(found)((void(*)(void*,unsigned char,unsigned char,unsigned char))vt[12])(obj,g,index,edit.value);
                if(!found&&edit.value){unsigned char value[3]={(unsigned char)g,(unsigned char)index,(unsigned char)edit.value};((void*(*)(void*,void*,const void*))at(0x4bbc470))(obj+0x130,end,value);}
            }
        }else if(edit.kind==31){
            if(edit.value!=0xffffffff&&edit.value>=team[0x72d])return false;
            auto manager=*(unsigned char**)(team+0x630);
            *(uint32_t*)(manager+0x8e8)=edit.value==0xffffffff?0x4e554c4c:person_key(original_roster[edit.side][edit.value]);
        }else if(edit.kind==13){
            if(edit.value>1)return false;
        }else if(edit.kind==12){
            if(edit.a>=11||edit.value>=11)return false;
            auto manager=*(unsigned char**)(team+0x630);
            // Serialized player -> OOP cell input, explicitly supplied when
            // importing a fresh recording; original preparation copies it.
            manager[0x1fb4+edit.a]=(unsigned char)edit.value;
        }else if(edit.kind==11){
            if(edit.a>=11||edit.value>=team[0x72d])return false;
        }else if(edit.kind==10){
            if(edit.value>1)return false;
            if(!tactics_only){
                auto manager=*(unsigned char**)(team+0x630);
                // Serialized manager input bit 0 selects the supplied-plan
                // path (49dc330); low bits zero select AI regeneration (df500).
                auto flags=(uint32_t*)(manager+0x30a0);
                *flags=(*flags&~1u)|edit.value;
            }
        }else return false;
    }
    for(unsigned side=0;side<2;side++)if(game_constraints[side]){
        scenario_stage="game_constraints";
        auto team=*(unsigned char**)(match+0x15380+side*8);auto manager=*(unsigned char**)(team+0x630);
        bool seen_mapping[11]={};for(unsigned i=0;i<11;i++){unsigned mapped=manager[0x1fb4+i];if(mapped==255)mapped=i;if(mapped>=11||seen_mapping[mapped])return false;seen_mapping[mapped]=true;}
        uint64_t bits=0;memcpy(&bits,creator[side],8);
        if(((bits>>25&1)&&(bits&0x70000000ULL))||((bits>>26&1)&&(bits&0x30000000ULL))||((bits>>27&1)&&(bits&0x50000000ULL)))return false;
        for(unsigned phase=0;phase<2;phase++)for(unsigned i=0;i<11;i++){
            auto cell=tactic_cell(manager,phase*16+i);uint32_t position=*(uint32_t*)cell;
            uint64_t role=*(uint64_t*)(cell+0x40)&0xfffffffbf91fffffULL;
            unsigned count=0,dm=0;for(unsigned j=0;j<11;j++){auto pos=*(uint32_t*)tactic_cell(manager,phase*16+j);if(pos&16)count++;if(pos&128)dm++;}
            auto allowed=((uint64_t(*)(const uint32_t*,unsigned))at(phase?0xc3220:0x1711a50))(&position,count);
            if(phase&&(position&128)&&dm==1)allowed&=~0x20000ULL;
            if(!role||(role&(role-1))||!(allowed&role)){fprintf(log_file,"{\"event\":\"invalid_role_context\",\"side\":%u,\"phase\":%u,\"position\":%u,\"role\":\"%llu\",\"allowed\":\"%llu\"}\n",side,phase,position,(unsigned long long)role,(unsigned long long)allowed);return false;}
        }
    }
    for(unsigned side=0;side<2;side++){
        scenario_stage="lineup";
        auto team=*(unsigned char**)(match+0x15380+8*side);unsigned lineup[11];bool requested=false,used[26]={};
        for(unsigned i=0;i<11;i++)lineup[i]=i;
        for(auto e:scenario_edits)if(e.kind==11&&e.side==side){lineup[e.a]=e.value;requested=true;}
        if(requested){
            for(auto i:lineup){if(used[i])return false;used[i]=true;}
            unsigned dest=0;for(auto i:lineup)*(unsigned char**)(team+0x138+8*dest++)=original_roster[side][i];
            for(unsigned i=0;i<team[0x72d];i++)if(!used[i])*(unsigned char**)(team+0x138+8*dest++)=original_roster[side][i];
        }
    }
    // Set the actual serialized input plans BEFORE native preparation. The
    // live-change API also rebuilds positions and is inappropriate for loading
    // an initial scenario. Leave compilation/normalization to native prepare.
    for(unsigned side=0;side<2;side++)if(changed[side]&&!tactics_only){
        auto team=*(unsigned char**)(match+0x15380+8*side);
        auto manager=*(unsigned char**)(team+0x630);
        for(unsigned offset:{0x18f8u,0x20a0u,0x2848u}){
            memcpy(manager+offset,creator[side],16);
            manager[offset+0x25]=creator[side][0x25];
        }
    }
    fprintf(log_file,"{\"event\":\"native_scenario_applied\",\"phase\":\"%s\",\"records\":%u,\"attributes\":%u,\"team_instructions\":%u}\n",tactics_only?"tactics_after_preparation":"attributes_before_preparation",count,attributes,instructions);fflush(log_file);
    return true;
}
static bool verify_scenario(unsigned char* match){
    if(scenario_file.empty())return true;
    for(const auto& edit:scenario_edits){
        auto team=*(unsigned char**)(match+0x15380+8*edit.side);
        auto manager=*(unsigned char**)(team+0x630);
        if(edit.kind==62){
            if(*(uint32_t*)(match+0xa3a)!=edit.value)return false;
            for(unsigned side=0;side<2;side++){
                auto prepared=*(unsigned char**)(*(unsigned char**)(match+0x15380+8*side)+0x630);
                for(auto offset:pi_policy_version_offsets)if(*(uint32_t*)(prepared+0x1818+offset)!=edit.value)return false;
            }
        }
        if(edit.kind==1){auto player=original_roster[edit.side][edit.a];if(player[0x480+edit.b]!=edit.value)return false;}
        if(edit.kind==17&&team[0x72d]!=edit.value)return false;
        if(edit.kind==18){
            auto cell=tactic_cell(manager,edit.a);auto entry=instruction_entry(cell,false);uint64_t expected=0;
            for(auto setting:scenario_edits)if(setting.kind==6&&setting.side==edit.side&&setting.a==edit.a&&setting.value)expected|=1ULL<<setting.value;
            if(!entry||entry[1]!=expected)return false;
        }
        if(edit.kind==15&&!profile_value(original_roster[edit.side][edit.a],edit.b,edit.value,false,team)){fprintf(log_file,"{\"event\":\"profile_readback_mismatch\",\"side\":%u,\"player\":%u,\"field\":%u}\n",edit.side,edit.a,edit.b);return false;}
        if(edit.kind==10&&((*(uint32_t*)(manager+0x30a0)&1)!=edit.value))return false;
        if(edit.kind==14){for(bool canonical:{false,true}){auto cell=tactic_cell(manager,edit.a,canonical);if((*(uint64_t*)(cell+0x40)&~0xfffffffbf91fffffULL)!=(((uint64_t)edit.b<<32)|edit.value))return false;}}
        if(edit.kind==20&&packed_oi(manager+0x16f8+edit.a*3)!=edit.value)return false;
        if(edit.kind==21){
            bool found=false;for(unsigned i=0;i<manager[0x1748];i++){auto row=manager+0x174c+i*8;if(*(uint32_t*)row==edit.a&&packed_oi(row+4)==edit.value)found=true;}if(!found)return false;
        }
        if(edit.kind==40){auto vec=routine_vector(manager,edit.a);if(!vec||size_t(*(void***)(vec+8)-*(void***)vec)!=edit.value)return false;}
        if(edit.kind==46){
            if(manager[0x16f0+edit.a]!=edit.value)return false;
            uint32_t expected=edit.a==2?(edit.value?0x54464c4f:0x54465348):(edit.value?0x544f574c:0x544f5242);
            auto actual=((uint32_t(*)(void*,unsigned char,unsigned char,size_t))at(0x1ba2a30))(manager+0x8f0,9,edit.a,0);
            if(actual!=expected)return false;
            fprintf(log_file,"{\"event\":\"native_throw_strategy_verified\",\"side\":%u,\"zone\":%u,\"preset\":%u}\n",edit.side,edit.a,actual);
        }
        if(edit.kind>=41&&edit.kind<=45){
            auto obj=routine(manager,edit.a);if(!obj)return false;auto vt=*(void***)obj;
            if(edit.kind==41){unsigned actual=edit.b==0?obj[0x14]:((unsigned char(*)(void*))vt[18+edit.b-1])(obj);if(actual!=edit.value)return false;}
            if(edit.kind==42){
                unsigned total=0;
                for(unsigned g=0;g<8;g++){
                    std::vector<unsigned char> expected;for(auto e:scenario_edits)if(e.kind==43&&e.side==edit.side&&e.a==edit.a&&e.b==g)expected.push_back((unsigned char)e.value);
                    unsigned char* group=nullptr;for(unsigned j=0;j<8;j++)if(obj[0x18+j*0x20]==g)group=obj+0x18+j*0x20;if(!group)return false;
                    auto begin=*(unsigned char**)(group+8),end=*(unsigned char**)(group+16);
                    if(size_t(end-begin)!=expected.size()||!std::equal(expected.begin(),expected.end(),begin))return false;total+=(unsigned)expected.size();
                    if(((unsigned(*)(void*,unsigned char))vt[14])(obj,(unsigned char)g)!=expected.size())return false;
                }
                std::vector<unsigned char> expected;for(auto e:scenario_edits)if(e.kind==44&&e.side==edit.side&&e.a==edit.a)expected.push_back((unsigned char)e.value);
                auto begin=*(unsigned char**)(obj+0x118),end=*(unsigned char**)(obj+0x120);
                if(size_t(end-begin)!=expected.size()||!std::equal(expected.begin(),expected.end(),begin))return false;
                fprintf(log_file,"{\"event\":\"native_setpiece_routine_verified\",\"side\":%u,\"type\":%u,\"variant\":%u,\"assignments\":%u}\n",edit.side,edit.a/16,edit.a%16,total);
            }
            if(edit.kind==45){unsigned value=0;auto begin=*(unsigned char**)(obj+0x130),end=*(unsigned char**)(obj+0x138);for(auto p=begin;p<end;p+=3)if(p[0]==edit.b/32&&p[1]==edit.b%32){value=p[2];break;}if(value!=edit.value)return false;}
        }
        if(edit.kind==30){auto list=priority_list(manager,edit.a);if(!list)return false;auto begin=*(uint32_t**)list,end=*(uint32_t**)(list+8);
            if(edit.b!=0xffffffff&&(end-begin<=edit.b||begin[edit.b]!=person_key(original_roster[edit.side][edit.value])))return false;
            if(edit.b==0xffffffff){unsigned expected=0;for(auto e:scenario_edits)if(e.kind==30&&e.side==edit.side&&e.a==edit.a&&e.b!=0xffffffff)expected++;if(end-begin!=expected)return false;
                fprintf(log_file,"{\"event\":\"native_priority_list_verified\",\"side\":%u,\"list\":%u,\"count\":%u}\n",edit.side,edit.a,expected);
            }
        }
        if(edit.kind==31&&edit.value!=0xffffffff){
            unsigned slot=manager[0x34e5];if(slot>=11||*(unsigned char**)(team+0x138+slot*8)!=original_roster[edit.side][edit.value])return false;
            fprintf(log_file,"{\"event\":\"native_captain_verified\",\"side\":%u,\"player_slot\":%u,\"person_key\":%u}\n",edit.side,slot,person_key(original_roster[edit.side][edit.value]));
        }
        if(edit.kind==11&&*(unsigned char**)(team+0x138+edit.a*8)!=original_roster[edit.side][edit.value])return false;
        if(edit.kind==12){
            for(unsigned plan:{0x1818u,0x2768u}){auto mapped=manager[plan+0x79c+edit.a];if((mapped==255?edit.a:mapped)!=edit.value)return false;}
        }
        if(edit.kind>=4&&edit.kind<=7){
            for(bool canonical:{false,true}){
                auto cell=tactic_cell(manager,edit.a,canonical);
                if(edit.kind==4&&(*(uint64_t*)(cell+0x40)&0xfffffffbf91fffffULL)!=(((uint64_t)edit.b<<32)|edit.value))return false;
                if(edit.kind==5&&*(uint32_t*)cell!=edit.value)return false;
                if(edit.kind==6){
                    auto entry=instruction_entry(cell,false);if(!entry)return false;
                    for(auto option:fm27_player_options)if(option.group==edit.b&&option.value){
                        if(bool(entry[1]&(1ULL<<option.value))!=(option.value==edit.value))return false;
                    }
                }
                if(edit.kind==7){auto e=instruction_entry(cell,false);if(!e)return false;
                    if(edit.b==0&&((unsigned char*)e)[20]!=edit.value)return false;
                    if(edit.b==1&&*(uint32_t*)((unsigned char*)e+16)!=edit.value)return false;
                }
            }
        }
        if(edit.kind==47){auto obj=routine(manager,edit.a);if(!obj||obj[0x15]!=edit.value)return false;}
        if(edit.kind==60){for(unsigned offset:{0x18f8u,0x2848u})if(((manager[offset+edit.a/8]>>(edit.a%8))&1)!=edit.value)return false;}
        if(edit.kind==2){
            unsigned bit=((unsigned(*)(unsigned))at(0x6687d0))(edit.value);
            for(const auto& option:fm27_team_options)if(option.group==edit.a&&option.bit){
                bool value=(manager[0x2848+option.bit/8]>>(option.bit%8))&1;
                bool active_value=(manager[0x18f8+option.bit/8]>>(option.bit%8))&1;
                if(value!=(option.bit==bit)||active_value!=value){fprintf(log_file,"{\"event\":\"scenario_bit_mismatch\",\"bit\":%u,\"canonical\":%s,\"active\":%s,\"expected\":%s}\n",option.bit,value?"true":"false",active_value?"true":"false",option.bit==bit?"true":"false");fflush(log_file);return false;}
            }
        }
        if(edit.kind==3&&manager[0x286d]!=edit.value)return false;
    }
    unsigned oi_checks=0;
    for(unsigned side=0;side<2;side++){
        auto own=*(unsigned char**)(match+0x15380+8*side),other=*(unsigned char**)(match+0x15380+8*(1-side));auto manager=*(unsigned char**)(own+0x630);
        for(unsigned i=0;i<11;i++){
            auto player=*(unsigned char**)(other+0x138+i*8);uint32_t position=*(uint32_t*)(player+0xce0);unsigned char actual[3]={};
            ((void(*)(void*,void*,uint64_t,uint32_t*))at(0x493a280))(manager+0x16f8,actual,i,&position);
            auto expected=manager+0x16f8+i*3;
            unsigned char fallback[3]={0,0,8};
            if(!(expected[2]&8)){expected=fallback;for(unsigned j=0;j<manager[0x1748];j++){auto row=manager+0x174c+j*8;if(*(uint32_t*)row==position){expected=row+4;break;}}}
            if(packed_oi(actual)!=packed_oi(expected))return false;oi_checks++;
        }
    }
    fprintf(log_file,"{\"event\":\"native_opposition_effective_verified\",\"players\":%u}\n",oi_checks);
    // Read the state copied into the actual MATCH_PLAYER objects, rather than
    // only the manager's input/canonical plans. OOP cells are permuted per player.
    for(unsigned side=0;side<2;side++){
        auto team=*(unsigned char**)(match+0x15380+side*8);auto manager=*(unsigned char**)(team+0x630);
        for(unsigned i=0;i<11;i++){
            auto player=*(unsigned char**)(team+0x138+i*8);unsigned mapped=manager[0x1fb4+i];if(mapped==255)mapped=i;
            if(mapped>=11)return false;
            for(unsigned phase=0;phase<2;phase++){
                auto input=tactic_cell(manager,phase*16+(phase?mapped:i));auto actual=player+(phase?0xdb8:0xce0);
                if(*(uint32_t*)input!=*(uint32_t*)actual||(*(uint64_t*)(input+0x40)&0xfffffffbf91fffffULL)!=(*(uint64_t*)(actual+0x40)&0xfffffffbf91fffffULL)){
                    fprintf(log_file,"{\"event\":\"player_tactic_binding_mismatch\",\"side\":%u,\"player_slot\":%u,\"phase\":%u,\"input_position\":%u,\"actual_position\":%u}\n",side,i,phase,*(uint32_t*)input,*(uint32_t*)actual);fflush(log_file);return false;
                }
                auto src=instruction_entry(input,false),dst=instruction_entry(actual,false);
                if(bool(src)!=bool(dst))return false;
                if(src&&(src[1]!=dst[1]||*(uint32_t*)((unsigned char*)src+16)!=*(uint32_t*)((unsigned char*)dst+16)||((unsigned char*)src)[20]!=((unsigned char*)dst)[20]))return false;
            }
        }
    }
    for(unsigned side=0;side<2;side++)for(unsigned phase=0;phase<2;phase++){
        auto team=*(unsigned char**)(match+0x15380+side*8);auto manager=*(unsigned char**)(team+0x630);uint64_t lo=0,hi=0;
        for(auto group:fm27_team_instruction_phases)if(group.phase==phase)for(auto option:fm27_team_options)if(option.group==group.group&&option.bit&&(manager[0x18f8+option.bit/8]>>(option.bit%8)&1)){
            if(option.bit<64)lo|=1ULL<<option.bit;else hi|=1ULL<<(option.bit-64);
        }
        fprintf(log_file,"{\"event\":\"native_phase_configuration\",\"side\":%u,\"phase\":%u,\"team_flags_low\":\"%llu\",\"team_flags_high\":\"%llu\",\"players\":",side,phase,(unsigned long long)lo,(unsigned long long)hi);
        log_phase_players(team,phase);fputs("}\n",log_file);
    }
    unsigned profile_fields=0;for(auto edit:scenario_edits)if(edit.kind==15)profile_fields++;
    fprintf(log_file,"{\"event\":\"native_profile_bindings_verified\",\"fields\":%u}\n",profile_fields);
    fprintf(log_file,"{\"event\":\"native_player_tactic_bindings_verified\",\"players\":22,\"phases\":2}\n");
    fprintf(log_file,"{\"event\":\"native_scenario_readback_verified\",\"records\":%llu,\"after_original_preparation\":true}\n",(unsigned long long)scenario_edits.size());fflush(log_file);
    return true;
}
static const char* native_type(void* pointer){
    MEMORY_BASIC_INFORMATION memory={};
    if(!VirtualQuery(pointer,&memory,sizeof(memory))||memory.State!=MEM_COMMIT||(memory.Protect&(PAGE_NOACCESS|PAGE_GUARD)))return nullptr;
    auto vtable=*(uintptr_t*)pointer,base=(uintptr_t)native_base;
    if(vtable<base+8||vtable>=base+434540544)return nullptr;
    auto col=*(uintptr_t*)(vtable-8);
    if(col<base||col+24>=base+434540544||*(uint32_t*)col!=1)return nullptr;
    auto descriptor=*(uint32_t*)(col+12);
    if(descriptor+256>=434540544)return nullptr;
    auto name=(char*)at(descriptor+16);
    return strncmp(name,".?A",3)?nullptr:name;
}
static void dump_match_input(unsigned char* match){
    if(dump_input.empty())return;
    FILE* f=_wfsopen(dump_input.c_str(),L"w",_SH_DENYNO);if(!f)ExitProcess(105);
    auto hex=[&](const void* p,size_t n){fputc('"',f);for(size_t i=0;i<n;i++)fprintf(f,"%02x",((const unsigned char*)p)[i]);fputc('"',f);};
    auto objects=[&](const char* owner,unsigned char* root,size_t size){
        for(size_t offset=0;offset+8<=size;offset+=8){
            auto p=*(void**)(root+offset);auto type=native_type(p);if(!type)continue;
            fprintf(f,"{\"owner\":\"%s\",\"offset\":%llu,\"type\":\"%s\",\"vtable_rva\":%llu,\"methods\":[",owner,(unsigned long long)offset,type,*(uint64_t*)p-(uintptr_t)native_base);
            auto vt=*(uint64_t**)p;for(int i=0;i<8;i++)fprintf(f,"%s%llu",i?",":"",vt[i]-(uintptr_t)native_base);fputs("]},",f);
        }
    };
    fputs("{\"objects\":[",f);objects("match",match,0x155b0);
    auto queued_begin=*(unsigned char**)(match+0x14800),queued_end=*(unsigned char**)(match+0x14808);
    if(queued_end-queued_begin>0&&queued_end-queued_begin<65536)objects("queued",queued_begin,queued_end-queued_begin);
    for(unsigned side=0;side<2;side++){auto team=*(unsigned char**)(match+0x15380+8*side);objects(side?"away":"home",team,0x738);objects(side?"away_player0":"home_player0",*(unsigned char**)(team+0x138),0x1e60);}
    fputs("null],\"teams\":[",f);
    for(unsigned side=0;side<2;side++){
        auto team=*(unsigned char**)(match+0x15380+8*side);
        unsigned count=team[0x72d];if(count>26)ExitProcess(106);
        fprintf(f,"%s{\"side\":%u,\"count\":%u,\"header_hex\":",side?",":"",side,count);hex(team,0x138);
        auto manager=*(unsigned char**)(team+0x630);
        fputs(",\"creator_hex\":",f);hex(manager+0x2848,0x28);
        fprintf(f,",\"manager_input_flags\":%u",*(uint32_t*)(manager+0x30a0));
        fputs(",\"manager_tactical_hex\":",f);hex(manager+0x2e0,0x2c30);
        fputs(",\"tactical_slots\":[",f);
        for(unsigned phase=0;phase<2;phase++){
            fprintf(f,"%s[",phase?",":"");
            for(unsigned slot=0;slot<11;slot++){if(slot)fputc(',',f);hex(manager+0x2768+(phase?0x438:0x118)+slot*0x48,0x48);}fputc(']',f);
        }
        fputc(']',f);
        fputs(",\"opposition\":[",f);
        for(unsigned i=0;i<26;i++)fprintf(f,"%s%u",i?",":"",manager[0x16f8+i*3]|(manager[0x16f9+i*3]<<8)|(manager[0x16fa+i*3]<<16));
        fputs("],\"opposition_positions\":[",f);
        for(unsigned i=0;i<manager[0x1748];i++){auto e=manager+0x174c+i*8;fprintf(f,"%s{\"position\":%u,\"packed\":%u}",i?",":"",*(uint32_t*)e,e[4]|(e[5]<<8)|(e[6]<<16));}
        fputs("],\"taker_lists\":[",f);
        unsigned list_index=0;
        for(unsigned off:{0u,0x18u,0x30u,0x48u,0x60u,0x78u,0x90u,0xa8u,0xc0u,0xd8u,0xf0u,0x108u,0x120u,0x138u,0x150u,0x168u,0x180u,0x198u,0x1c8u,0x1e0u}){
            auto v=manager+0x6f0+off;auto begin=*(uint32_t**)v,end=*(uint32_t**)(v+8);
            if(end-begin>10000)ExitProcess(106);
            fprintf(f,"%s{\"offset\":%u,\"players\":[",list_index++?",":"",off);
            for(auto p=begin;p<end;p++)fprintf(f,"%s%u",p==begin?"":",",*p);fputs("]}",f);
        }
        fputs("],\"routine_objects\":[",f);unsigned found=0;
        for(unsigned off=0x8f0;off<0x16f8;off+=8){auto type=native_type(manager+off);if(type&&strstr(type,"SET_PIECE")){
            fprintf(f,"%s{\"offset\":%u,\"type\":\"%s\",\"vtable_rva\":%llu,\"data\":",found++?",":"",off,type,*(uint64_t*)(manager+off)-(uintptr_t)native_base);hex(manager+off,96);fputc('}',f);
        }}fputc(']',f);
        fputs(",\"routine_variants\":[",f);
        for(unsigned group=0;group<10;group++){
            auto vec=manager+0x8f0+0xd10+24*group;auto begin=*(unsigned char***)vec,end=*(unsigned char***)(vec+8);
            fprintf(f,"%s[",group?",":"");
            for(auto ptr=begin;ptr<end;ptr++){
                auto obj=*ptr;auto vt=*(void***)obj;unsigned type=((unsigned char(*)(void*))vt[6])(obj);
                fprintf(f,"%s{\"type\":%u,\"vtable\":%llu,\"frequency\":%u,\"strategy\":%u,\"swing\":%u,\"groups\":[",ptr==begin?"":",",type,*(uint64_t*)obj-(uintptr_t)native_base,obj[0x14],((unsigned char(*)(void*))vt[18])(obj),((unsigned char(*)(void*))vt[19])(obj));
                for(unsigned j=0;j<8;j++){
                    auto entry=obj+0x18+j*0x20;auto a=*(unsigned char**)(entry+8),b=*(unsigned char**)(entry+16);
                    fprintf(f,"%s{\"id\":%u,\"values\":[",j?",":"",*entry);for(auto p=a;p<b;p++)fprintf(f,"%s%u",p==a?"":",",*p);fputs("]}",f);
                }
                fprintf(f,"],\"opaque_flags\":%u,\"priority\":[",obj[0x15]);auto a=*(unsigned char**)(obj+0x118),b=*(unsigned char**)(obj+0x120);for(auto p=a;p<b;p++)fprintf(f,"%s%u",p==a?"":",",*p);
                fputs("],\"backups\":[",f);a=*(unsigned char**)(obj+0x130);b=*(unsigned char**)(obj+0x138);for(auto p=a;p<b;p+=3)fprintf(f,"%s[%u,%u,%u]",p==a?"":",",p[0],p[1],p[2]);fputs("]}",f);
            }fputc(']',f);
        }fputc(']',f);
        fputs(",\"personal_instructions\":[",f);
        for(unsigned phase=0;phase<2;phase++){
            fprintf(f,"%s[",phase?",":"");
            for(unsigned slot=0;slot<11;slot++){
                auto cell=tactic_cell(manager,phase*16+slot,true);auto e=instruction_entry(cell,false);
                fprintf(f,"%s{\"flags\":\"%llu\",\"target_position\":%u,\"target_player\":%u}",slot?",":"",e?e[1]:0,e?*(uint32_t*)((unsigned char*)e+16):0,e?((unsigned char*)e)[20]:255);
            }fputc(']',f);
        }fputc(']',f);
        fputs(",\"instructions\":[",f);auto first=*(uint32_t**)(team+0x68),last=*(uint32_t**)(team+0x70);
        if(last-first>512)ExitProcess(106);
        for(auto p=first;p<last;p+=4)fprintf(f,"%s[%u,%u,%u,%u]",p==first?"":",",p[0],p[1],p[2],p[3]);
        fputs("],\"players\":[",f);
        for(unsigned i=0;i<count;i++){
            auto player=*(unsigned char**)(team+0x138+i*8);
            fprintf(f,"%s{\"index\":%u,\"id\":%u,\"person_key\":%u,\"prefix_hex\":",i?",":"",i,*(uint32_t*)(player+0x50),person_key(player));hex(player,0x80);
            fputs(",\"state_hex\":",f);hex(player+0x2e0,0x200);
            fputs(",\"identity_extra_hex\":",f);hex(player+0x80,0x200);
            fputs(",\"input_tail_hex\":",f);hex(player+0x4c5,0x81b);
            fprintf(f,",\"foot_runtime\":[%d,%d]",*(int*)(player+0x1bf0),*(int*)(player+0x1c80));
            fputs(",\"attributes\":[",f);for(unsigned a=0;a<69;a++)fprintf(f,"%s%u",a?",":"",player[0x480+a]);fputs("]}",f);
        }
        fputs("]}",f);
    }
    fputs("]}\n",f);fclose(f);
}
#include "fm27_engine_compat.h"
static char native_image_sha256[65]={};
static bool fingerprint_image(const fs::path& path){
    BCRYPT_ALG_HANDLE algorithm=nullptr;BCRYPT_HASH_HANDLE hash=nullptr;
    if(BCryptOpenAlgorithmProvider(&algorithm,BCRYPT_SHA256_ALGORITHM,nullptr,0)<0)return false;
    if(BCryptCreateHash(algorithm,&hash,nullptr,0,nullptr,0,0)<0){BCryptCloseAlgorithmProvider(algorithm,0);return false;}
    std::ifstream file(path,std::ios::binary);std::vector<unsigned char> block(1024*1024);
    bool okay=file.good();
    while(file){file.read((char*)block.data(),block.size());auto n=file.gcount();if(n&&BCryptHashData(hash,block.data(),(ULONG)n,0)<0)okay=false;}
    if(!file.eof())okay=false;
    unsigned char digest[32]={};if(BCryptFinishHash(hash,digest,32,0)<0)okay=false;
    BCryptDestroyHash(hash);BCryptCloseAlgorithmProvider(algorithm,0);
    auto hex=native_image_sha256;for(int i=0;i<32;i++)sprintf_s(hex+i*2,3,"%02x",digest[i]);
    fprintf(log_file,"{\"event\":\"native_image_fingerprint\",\"sha256\":\"%s\"}\n",hex);fflush(log_file);
    wchar_t expected[128]={};if(GetEnvironmentVariableW(L"FM27_EXPECTED_DLL_SHA256",expected,128)){
        std::wstring actual(hex,hex+64);if(actual!=expected){fputs("{\"event\":\"engine_changed_within_session\"}\n",log_file);return false;}
    }
    return okay;
}
static bool known_image(const fs::path& path){
#ifdef FM27_COMPAT_DIGEST_RANGES
    if(!fingerprint_image(path)||strcmp(native_image_sha256,epic_reference_sha256)){
        fprintf(log_file,"{\"event\":\"native_engine_compatibility\",\"compatible\":false,\"trial_allowed\":false,\"reason\":\"epic_build_fingerprint_mismatch\"}\n");
        fflush(log_file);
        return false;
    }
    return compatible_image(path);
#else
    return compatible_image(path)&&fingerprint_image(path);
#endif
}
#include "native_statistics.h"
#include "native_fmf_probe.h"
#include "native_tactic_import.h"
#include "native_tactic_export.h"
#include "native_match_events.h"
#include "native_setpiece_file.h"
#include "native_setpiece_episode.h"
#include "native_saved_fixture.h"
#include "native_ai_tactics.h"
#include "native_source_generation.h"
#include "native_source_staff.h"
#include "native_coach_presets.h"
#include "native_execution_experiment.h"
static int native_match(void* interface_object){
    fprintf(log_file,"{\"event\":\"native_match_pipeline_started\",\"runtime\":\"native_library_host\",\"full_match_completed\":false}\n");fflush(log_file);
    std::ifstream input(fixture,std::ios::binary);
    std::vector<unsigned char> bytes(std::istreambuf_iterator<char>(input),{});
    if(bytes.size()<12||bytes.size()>64*1024*1024)desktop_finish_and_exit(87);
    void* reference=nullptr;
    *(void**)at(0x581cab0)=interface_object;
    if(!worker_bootstrapped){
    SetCurrentDirectoryW(bundle.c_str());
    auto platform=((unsigned char(*)(unsigned int))at(0x9fa910))(3);
    fprintf(log_file,"{\"event\":\"native_platform_initialized\",\"accepted\":%s}\n",platform?"true":"false");fflush(log_file);
    if(!platform)desktop_finish_and_exit(94);
    // The game normally supplies ICU common data through its file manager.
    // The headless host supplies the unchanged original common-data file.
    auto icu=GetModuleHandleW(L"icuuc65.dll");
    if(!icu)desktop_finish_and_exit(103);
    auto set_data=(void(*)(const void*,int*))GetProcAddress(icu,"udata_setCommonData_65");
    auto initialize=(void(*)(int*))GetProcAddress(icu,"u_init_65");
    auto data_version=(void(*)(unsigned char*,int*))GetProcAddress(icu,"u_getDataVersion_65");
    if(!set_data||!initialize||!data_version)desktop_finish_and_exit(103);
    std::ifstream icu_file((desktop_game_root.empty()?bundle:desktop_game_root)/L"icudt65l.dat",std::ios::binary);
    std::vector<char> icu_bytes(std::istreambuf_iterator<char>(icu_file),{});
    if(icu_bytes.size()<32)desktop_finish_and_exit(103);
    auto payload=VirtualAlloc(nullptr,icu_bytes.size(),MEM_COMMIT|MEM_RESERVE,PAGE_READWRITE);
    if(!payload)desktop_finish_and_exit(103);
    memcpy(payload,icu_bytes.data(),icu_bytes.size());
    DWORD old_protection=0;VirtualProtect(payload,icu_bytes.size(),PAGE_READONLY,&old_protection);
    int icu_status=0;set_data(payload,&icu_status);initialize(&icu_status);
    unsigned char version[4]={};data_version(version,&icu_status);
    fprintf(log_file,"{\"event\":\"host_icu_data_initialized\",\"status\":%d,\"data_version\":[%u,%u,%u,%u]}\n",icu_status,version[0],version[1],version[2],version[3]);fflush(log_file);
    if(icu_status>0)desktop_finish_and_exit(103);
    // Resource and structured-data managers, constructed by original native
    // constructors from a29424..a2943e and a18a88..a18aa2.
    auto native_alloc=(void*(*)(size_t))at(0x4940da0);
    if(!*(void**)at(0x580eb40)){
        auto manager=native_alloc(0x110);((void*(*)(void*))at(0xc70910))(manager);
        *(void**)at(0x580eb40)=manager;
    }
    if(!*(void**)at(0x580ec68)){
        auto manager=native_alloc(0x10);((void*(*)(void*))at(0xe25b60))(manager);
        *(void**)at(0x580ec68)=manager;
        ((void(*)())at(0x35558d0))();
    }
    auto resources=*(void**)at(0x580eb40);
    ((void(*)(void*,void*))at(0xc71eb0))(resources,at(0x581e6a0));
    // Canonical JSON resource type; its native initializer handles the binary
    // and text resource readers used by the original match data.
    ((void(*)(void*,void*))at(0xc723c0))(resources,at(0x5831568));
    desktop_coach_preset_resource_types(resources);
    ((void(*)(void*))at(0xc72460))(resources);
    auto type_begin=((uintptr_t*)resources)[0x60/8],type_end=((uintptr_t*)resources)[0x68/8];
    fprintf(log_file,"{\"event\":\"native_resource_type_count\",\"count\":%llu}\n",(unsigned long long)((type_end-type_begin)/8));fflush(log_file);
    // Register the extracted original asset folders through the native root
    // API used by the application's normal resource discovery routine.
    for(const char* relative:{"shared/data/simatch.fmf","shared/data/simatchshared.fmf"}){
        auto path=((desktop_game_root.empty()?bundle:desktop_game_root)/relative).generic_u8string();
        uintptr_t name[4]={};((void*(*)(void*,const char*,int))at(0x122880))(name,path.c_str(),-1);
        void* file=nullptr;void* folder=nullptr;
        ((void*(*)(void*,void*,void*))at(0x39f72a0))(&file,name,(unsigned char*)resources+0xc0);
        ((void*(*)(void*,void*,uintptr_t))at(0x148bac0))(&folder,&file,*(uintptr_t*)at(0x5824c90));
        fprintf(log_file,"{\"event\":\"native_archive_opened\",\"success\":%s}\n",folder?"true":"false");fflush(log_file);
        if(folder){
            auto methods=*(void***)folder;uintptr_t folder_path[4]={};
            ((void*(*)(void*,void*))methods[4])(folder,folder_path);
            ((void(*)(void*,void*,void*))at(0xc733d0))(resources,folder_path,at(0x5831968));
        }
    }
    auto root_bytes=(uintptr_t)((unsigned char**)resources)[0x80/8]-(uintptr_t)((unsigned char**)resources)[0x78/8];
    fprintf(log_file,"{\"event\":\"native_asset_roots_registered\",\"count\":%llu}\n",(unsigned long long)(root_bytes/0x30));fflush(log_file);
    for(auto position=(unsigned char*)((uintptr_t*)resources)[0x78/8];position<(unsigned char*)((uintptr_t*)resources)[0x80/8];position+=0x30){
        auto item=*(void**)position;auto vtable=*(void***)item;uintptr_t text=0;
        ((void*(*)(void*,void*))vtable[4])(item,&text);
        auto directory=((unsigned char(*)(void*))vtable[5])(item);
        auto data=(unsigned int*)text;
        fprintf(log_file,"{\"event\":\"native_asset_root_info\",\"directory\":%s,\"path\":\"%.*s\"}\n",directory?"true":"false",data?std::min(*data,256u):0,data?(char*)(data+1):"");fflush(log_file);
    }
    desktop_probe_fmf(resources);
    int scan_status[8]={};((void*(*)(void*,void*))at(0xc73ab0))(resources,scan_status);
    fprintf(log_file,"{\"event\":\"native_resource_index_built\",\"status\":%d,\"indexed_keys\":%llu}\n",scan_status[0],((unsigned long long*)resources)[0x58/8]);fflush(log_file);
    uintptr_t query[2]={},folder_list[3]={};
    ((void*(*)(void*,void*))at(0x1266b0))(query,at(0x58340c8));
    auto folder_found=((unsigned char(*)(void*,void*,void*))at(0x126a00))(resources,query,folder_list);
    fprintf(log_file,"{\"event\":\"native_xg_folder_probe\",\"found\":%s,\"entries\":%llu}\n",folder_found?"true":"false",(unsigned long long)((folder_list[1]-folder_list[0])/8));fflush(log_file);
    if(scan_status[0]||!folder_found||folder_list[0]==folder_list[1])desktop_finish_and_exit(95);
    // Execute the complete original bootstrap, preserving its native default
    // input rather than manually setting its success/readiness flags.
    static unsigned char init_input[0x88];memcpy(init_input,at(0x5821530),sizeof(init_input));
    auto initialized=((unsigned char(*)(void*,void*))at(0x4ba15a0))(init_input,nullptr);
    fprintf(log_file,"{\"event\":\"native_engine_bootstrap_returned\",\"accepted\":%s}\n",initialized?"true":"false");fflush(log_file);
    if(!initialized)desktop_finish_and_exit(93);
    worker_bootstrapped=true;
    }else{fputs("{\"event\":\"native_worker_bootstrap_reused\"}\n",log_file);}
    auto resources=*(void**)at(0x580eb40);
    auto stats=*(uintptr_t**)at(0x58215b8);
    size_t versions=(stats[2]-stats[1])/32,models=0;
    for(auto p=stats[1];p<stats[2];p+=32){auto row=(uintptr_t*)p;models+=(row[2]-row[1])/32;}
    fprintf(log_file,"{\"event\":\"native_xg_models_parsed\",\"version_groups\":%llu,\"model_records\":%llu}\n",(unsigned long long)versions,(unsigned long long)models);fflush(log_file);
    if(!versions||!models)desktop_finish_and_exit(96);
    interface_object=*(void**)at(0x581cab0);
    // Open the PKM container with the same native reader factory as a84eec.
    // This delegates container decoding and stream/EOF semantics to FM itself.
    static std::map<std::string,std::array<uintptr_t,4>> recording_paths;
    auto entry=recording_paths.emplace(fixture.generic_u8string(),std::array<uintptr_t,4>{});
    auto recording_path=entry.first->second.data();
    if(entry.second)((void*(*)(void*,const char*,int))at(0x122880))(recording_path,entry.first->first.c_str(),-1);
    void* recording_file=nullptr;void* native_stream=nullptr;void* reader_extra=nullptr;
    ((void*(*)(void*,void*,void*))at(0x39f72a0))(&recording_file,recording_path,(unsigned char*)resources+0xc0);
    uint64_t reader_options[2]={0x80100004e554c4c,0};
    ((void*(*)(void*,void*,void*,uintptr_t,void*))at(0x144f520))(reader_options,&native_stream,&recording_file,0,&reader_extra);
    fprintf(log_file,"{\"event\":\"native_recording_stream_opened\",\"success\":%s}\n",native_stream?"true":"false");fflush(log_file);
    if(!native_stream)desktop_finish_and_exit(104);
    // The original caller copies its intrusive reference before the by-value
    // recording argument (a84f35..a84f42); preserve that ownership contract.
    InterlockedIncrement((volatile LONG*)((unsigned char*)native_stream+8));
    reference=native_stream;
    auto match=(unsigned char*)((void*(*)(size_t))at(0xa9fff0))(0x155b0);
    ((void*(*)(void*))at(0x15d080))(match);
    memcpy(duel_competition_defaults,match+0x678,0x30);
    fprintf(log_file,"{\"event\":\"native_match_constructed\"}\n");fflush(log_file);
    // Same derived benchmark class and thread context as original a84f12/a84f89.
    *(void**)match=at(0x4d8e888);match[0x155a0]=0;
    auto slots=(void**)__readgsqword(0x58);
    // Read the TLS-index RVA from the PE TLS directory rather than assuming it.
    auto dos=(IMAGE_DOS_HEADER*)native_base;auto nt=(IMAGE_NT_HEADERS64*)(native_base+dos->e_lfanew);
    auto tls_directory=(IMAGE_TLS_DIRECTORY64*)at(nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_TLS].VirtualAddress);
    auto index=*(unsigned int*)tls_directory->AddressOfIndex;
    auto tls=(unsigned char*)slots[index];
    if(!tls[0x4b8])((void(*)())at(0x4941140))();
    struct {void* match;uint64_t flags;} match_thread_context={match,0};
    *(void**)(tls+0x838)=&match_thread_context;
    auto accepted=((unsigned char(*)(void*,void*,void*,unsigned int))at(0x4bab520))(match,&reference,interface_object,0);
    fprintf(log_file,"{\"event\":\"native_fixture_deserialized\",\"accepted\":%s,\"input_adapter\":\"original_native\"}\n",accepted?"true":"false");fflush(log_file);
    if(!accepted)desktop_finish_and_exit(88);
    auto release_ref=[](void*& value){if(value){auto p=value;value=nullptr;if(InterlockedDecrement((volatile LONG*)((unsigned char*)p+8))==0)((void(*)(void*,unsigned))(*(void***)p)[0])(p,1);}};
    release_ref(reference);release_ref(native_stream);
    desktop_read_ai_tactics(match);
    desktop_export_coach_presets();
    staff_body_diagnostic();
    saved_section_probe(interface_object);
    desktop_import_tac(match);
    desktop_import_setpiece(match);
    if(!apply_scenario(match)){fprintf(log_file,"{\"event\":\"scenario_rejected\",\"stage\":\"%s\",\"kind\":%u,\"side\":%u,\"a\":%u,\"b\":%u,\"value\":%u}\n",scenario_stage,current_scenario_edit.kind,current_scenario_edit.side,current_scenario_edit.a,current_scenario_edit.b,current_scenario_edit.value);fflush(log_file);desktop_finish_and_exit(108);}
    desktop_export_tac(match);
    auto fixture_seed=*(uint32_t*)(match+0x20);
    if(seed_override)*(uint32_t*)(match+0x20)=requested_seed;
    fprintf(log_file,"{\"event\":\"native_input_seed\",\"fixture_seed\":%u,\"effective_seed\":%u,\"override\":%s}\n",fixture_seed,*(uint32_t*)(match+0x20),seed_override?"true":"false");fflush(log_file);
    source_generation_install(match);
    execution_install(match);
    timing_prepare=GetTickCount64();
    ((void(*)(void*))at(0x4b98f50))(match);
    timing_ready=GetTickCount64();
    for(const auto& edit:scenario_edits)if(edit.kind==17){
        auto team=*(unsigned char**)(match+0x15380+8*edit.side);
        if(edit.value<11||edit.value>team[0x72d])desktop_finish_and_exit(108);
        auto original_count=team[0x72d];team[0x72d]=(unsigned char)edit.value;
        fprintf(log_file,"{\"event\":\"native_match_roster_committed\",\"side\":%u,\"carrier_count\":%u,\"participants\":%u,\"after_original_preparation\":true}\n",edit.side,original_count,edit.value);fflush(log_file);
    }
    if(!verify_scenario(match)){fprintf(log_file,"{\"event\":\"scenario_readback_mismatch\"}\n");fflush(log_file);desktop_finish_and_exit(109);}
    source_generation_verified(match);
    dump_match_input(match);
    if(inspect_fixture_only){
        fputs("{\"event\":\"native_fixture_inspected\",\"simulation_ticks_executed\":0}\n",log_file);fflush(log_file);
        desktop_finish_and_exit(0);return 0;
    }
    desktop_initial_state_snapshot(match);
    fprintf(log_file,"{\"event\":\"native_preparation_returned\",\"gates\":[%u,%u,%u]}\n",match[0x15570],match[0x1556e],match[0x15575]);fflush(log_file);
    if(match[0x15570]!=1||match[0x1556e]!=1||match[0x15575]==0)desktop_finish_and_exit(89);
    desktop_stats_snapshot(match,"prepared");
    if(!desktop_events_start(match))desktop_finish_and_exit(181);
    auto score_context=*(unsigned char**)(match+0x14ea0);auto result=*(void**)(score_context+0x18);
    auto score=(unsigned char*(*)(void*,unsigned int))(*(void***)result)[5];
    desktop_episode_init();
    int previous_home=*score(result,0),previous_away=*score(result,1);
    fprintf(log_file,"{\"event\":\"native_score_before_simulation\",\"score\":[%d,%d]}\n",previous_home,previous_away);fflush(log_file);
    if(previous_home||previous_away)desktop_finish_and_exit(97);
    int observed_setpiece[2]={-1,-1};
    int previous_phase[2]={-1,-1};unsigned phase_changes[2]={};uint64_t phase_samples[2][2]={};
    for(unsigned iteration=0;iteration<100000;iteration++){
        int tick=*(int*)(match+0x154ec);unsigned flags=*(unsigned*)(match+0x15500);
        for(unsigned side=0;side<2;side++){
            auto team=*(unsigned char**)(match+0x15380+side*8);int code=*(int*)(team+0x718);unsigned phase=code==0?0:1;phase_samples[side][phase]++;
            if(previous_phase[side]!=(int)phase){
                previous_phase[side]=phase;phase_changes[side]++;
                if(phase_changes[side]<=8){
                    fprintf(log_file,"{\"event\":\"native_phase_cell_observation\",\"side\":%u,\"phase\":%u,\"state_code\":%d,\"tick\":%d,\"players\":",side,phase,code,tick);
                    log_phase_players(team,phase);fputs("}\n",log_file);
                }
            }
        }
        int home=*score(result,0),away=*score(result,1);
        unsigned deadball=match[0x12d70];
        if(deadball>=1&&deadball<=13&&(0x1f99u>>(deadball-1)&1u)){
            unsigned attacking_type=((unsigned char*)at(0x4f437f0))[deadball-1];
            auto taking=*(unsigned char**)(match+0x12d50);
            for(unsigned side=0;side<2;side++){
                auto team=*(unsigned char**)(match+0x15380+8*side);auto manager=*(unsigned char**)(team+0x630);
                unsigned type=attacking_type-(team==taking?0:5);
                unsigned variant=((unsigned(*)(void*,unsigned char))at(0x26b0c00))(manager,(unsigned char)type);
                if(variant>=3)continue;auto obj=routine(manager,type*16+variant);if(!obj)continue;
                int key=(int)(deadball*256+type*16+variant);
                if(key!=observed_setpiece[side]){
                    observed_setpiece[side]=key;auto vt=*(void***)obj;
                    fprintf(log_file,"{\"event\":\"native_setpiece_selected\",\"side\":%u,\"deadball\":%u,\"type\":%u,\"variant\":%u,\"frequency\":%u,\"strategy\":%u,\"swing\":%u,\"tick\":%d}\n",side,deadball,type,variant,obj[0x14],((unsigned char(*)(void*))vt[18])(obj),((unsigned char(*)(void*))vt[19])(obj),tick);
                }
            }
        }else observed_setpiece[0]=observed_setpiece[1]=-1;
        if(home!=previous_home||away!=previous_away){
            fprintf(log_file,"{\"event\":\"observed_score_change\",\"tick\":%d,\"clock\":%d,\"score\":[%d,%d],\"observation_step\":%d}\n",tick,*(int*)(match+0x15464),home,away,tick_step);fflush(log_file);
            previous_home=home;previous_away=away;
        }
        desktop_check_cancel();
        desktop_episode_step(match);
        if(flags&4){
            for(unsigned side=0;side<2;side++)fprintf(log_file,"{\"event\":\"native_phase_coverage\",\"side\":%u,\"in_possession_samples\":%llu,\"out_of_possession_samples\":%llu,\"phase_changes\":%u}\n",side,(unsigned long long)phase_samples[side][0],(unsigned long long)phase_samples[side][1],phase_changes[side]);
            desktop_stats_snapshot(match,"finished");
            execution_snapshot(match,"finished");
            desktop_match_statistics(match);
            desktop_player_totals(match);
            auto now=GetTickCount64();
            fprintf(log_file,"{\"event\":\"native_timings\",\"load_ms\":%llu,\"activation_ms\":%llu,\"input_bootstrap_ms\":%llu,\"preparation_ms\":%llu,\"simulation_ms\":%llu,\"total_ms\":%llu}\n",timing_loaded-timing_start,timing_active-timing_loaded,timing_prepare-timing_active,timing_ready-timing_prepare,now-timing_ready,now-timing_start);
            auto context=*(unsigned char**)(match+0x14ea0);auto result=*(void**)(context+0x18);
            auto vtable=*(void***)result;auto score=(unsigned char*(*)(void*,unsigned int))vtable[5];
            auto home=score(result,0),away=score(result,1);
            fprintf(log_file,"{\"event\":\"natural_match_finished\",\"full_match_completed\":true,\"runtime\":\"native_library_host\",\"extracted_engine\":false,\"tick\":%d,\"clock\":%d,\"score\":[%d,%d]}\n",tick,*(int*)(match+0x15464),home?*home:-1,away?*away:-1);fflush(log_file);
            // Native globals retain stack-owned ICU/context buffers. End the
            // isolated child after committing the result, before those buffers
            // are destroyed and before DLL detach can use invalid state.
            FlushFileBuffers((HANDLE)_get_osfhandle(_fileno(log_file)));
            if(!worker_manifest.empty()){
                if(!desktop_events_stop())desktop_finish_and_exit(181);
                execution_end_match();
                fputs("{\"event\":\"original_match_release_started\"}\n",log_file);fflush(log_file);
                ((void(*)(void*))(*(void***)interface_object)[1])(interface_object);
                ((void(*)(void*))at(0x4ba6800))(match);
                ((void(*)(void*))at(0xad9390))(match);
                release_ref(recording_file);
                if(*(void**)(tls+0x838)==&match_thread_context)*(void**)(tls+0x838)=nullptr;
                DWORD handles=0;GetProcessHandleCount(GetCurrentProcess(),&handles);
                fprintf(log_file,"{\"event\":\"original_match_release_completed\",\"tls_context_cleared\":%s,\"process_handles\":%lu}\n",*(void**)(tls+0x838)==nullptr?"true":"false",handles);fflush(log_file);
                return 0;
            }
            desktop_finish_and_exit(0);return 0;
        }
        // The target check precedes the forced-score watchdog in native run.
        // Every call stops below its entry threshold 47996; no engine patches.
        if(tick>=47995){fprintf(log_file,"{\"event\":\"watchdog_boundary_rejected\"}\n");fflush(log_file);desktop_finish_and_exit(90);}
        int target=std::min(tick+tick_step,47995);
        ((void(*)(void*,unsigned int,int))at(0x4764ac0))(match,1,target);
        int after=*(int*)(match+0x154ec);
        if(iteration%4096==0){fprintf(log_file,"{\"event\":\"native_match_progress\",\"tick\":%d,\"clock\":%d}\n",after,*(int*)(match+0x15464));fflush(log_file);}
        if(after==tick){fprintf(log_file,"{\"event\":\"native_match_stalled\",\"tick\":%d}\n",tick);fflush(log_file);desktop_finish_and_exit(91);}
    }
    desktop_finish_and_exit(92);
}
static void debug_text(EXCEPTION_RECORD* p){
    char text[8192]={};
    if(p->ExceptionCode==0x40010006&&p->NumberParameters>=2){
        auto n=p->ExceptionInformation[0];if(n>2047)n=2047;
        auto source=(const char*)p->ExceptionInformation[1];wchar_t wide[2048]={};
        int length=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,source,(int)n,wide,2047);
        if(!length)length=MultiByteToWideChar(CP_ACP,0,source,(int)n,wide,2047);
        if(length)WideCharToMultiByte(CP_UTF8,0,wide,length,text,sizeof(text)-1,nullptr,nullptr);
    }else if(p->ExceptionCode==0x4001000a&&p->NumberParameters>=2){
        auto n=p->ExceptionInformation[0];if(n>511)n=511;
        WideCharToMultiByte(CP_UTF8,0,(wchar_t*)p->ExceptionInformation[1],(int)n,text,sizeof(text)-1,nullptr,nullptr);
    }else return;
    fprintf(log_file,"{\"event\":\"native_debug_text\",\"text\":\"");
    for(unsigned char* q=(unsigned char*)text;*q;q++){
        if(*q=='"'||*q=='\\')fputc('\\',log_file);
        if(*q=='\n')fputs("\\n",log_file);else if(*q=='\r')fputs("\\r",log_file);else if(*q>=32)fputc(*q,log_file);
    }
    fprintf(log_file,"\"}\n");fflush(log_file);
}
static LONG WINAPI observe(EXCEPTION_POINTERS* p){
    std::lock_guard<std::recursive_mutex> lock(worker_log_lock);
    fprintf(log_file,"{\"event\":\"exception\",\"code\":\"0x%lx\",\"address\":\"0x%llx\"}\n",p->ExceptionRecord->ExceptionCode,(unsigned long long)p->ExceptionRecord->ExceptionAddress);fflush(log_file);
    debug_text(p->ExceptionRecord);
    if(p->ExceptionRecord->ExceptionCode==EXCEPTION_ACCESS_VIOLATION){
        auto c=p->ContextRecord;HMODULE module=nullptr;wchar_t path[MAX_PATH]={};
        GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS|GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,(LPCWSTR)c->Rip,&module);
        if(module)GetModuleFileNameW(module,path,MAX_PATH);
        auto name=wcsrchr(path,L'\\');if(name)name++;else name=path;
        fprintf(log_file,"{\"event\":\"native_av_diagnostic\",\"module\":\"%ls\",\"rva\":\"0x%llx\",\"fault\":\"0x%llx\",\"access\":%llu,\"input_cursor\":%llu,\"input_reads\":%llu,\"rcx\":\"0x%llx\",\"rdx\":\"0x%llx\",\"r8\":\"0x%llx\",\"r9\":\"0x%llx\",\"rbx\":\"0x%llx\",\"rsi\":\"0x%llx\",\"rdi\":\"0x%llx\"}\n",name,c->Rip-(uintptr_t)module,p->ExceptionRecord->NumberParameters>1?p->ExceptionRecord->ExceptionInformation[1]:0,p->ExceptionRecord->ExceptionInformation[0],input_cursor,input_reads,c->Rcx,c->Rdx,c->R8,c->R9,c->Rbx,c->Rsi,c->Rdi);fflush(log_file);
        CONTEXT walk=*c;
        for(unsigned depth=0;depth<24&&walk.Rip;depth++){
            DWORD64 image=0;auto entry=RtlLookupFunctionEntry(walk.Rip,&image,nullptr);
            fprintf(log_file,"{\"event\":\"native_av_frame\",\"depth\":%u,\"pc\":\"0x%llx\",\"engine_rva\":\"0x%llx\"}\n",depth,walk.Rip,walk.Rip-(uintptr_t)native_base);fflush(log_file);
            if(entry){void* handler=nullptr;DWORD64 frame=0;RtlVirtualUnwind(UNW_FLAG_NHANDLER,image,walk.Rip,entry,&walk,&handler,&frame,nullptr);}
            else{
                MEMORY_BASIC_INFORMATION memory={};VirtualQuery((void*)walk.Rsp,&memory,sizeof(memory));
                if(memory.State!=MEM_COMMIT||(memory.Protect&(PAGE_NOACCESS|PAGE_GUARD)))break;
                walk.Rip=*(DWORD64*)walk.Rsp;walk.Rsp+=8;
            }
        }
    }
    return EXCEPTION_CONTINUE_SEARCH;
}

static int worker_loop(void* object){
    if(GetEnvironmentVariableW(L"FM27_DESKTOP_STATS_AUDIT",nullptr,0)||GetEnvironmentVariableW(L"FM27_EPISODE_TYPE",nullptr,0)||GetEnvironmentVariableW(L"FM27_IMPORT_FMF",nullptr,0)||GetEnvironmentVariableW(L"FM27_EXPORT_TAC",nullptr,0))return 184;
    std::ifstream manifest(worker_manifest);std::string line;
    if(!std::getline(manifest,line))return 184;
    bool counted=line=="FM27DW2";unsigned expected=64;
    if(counted){
        if(!std::getline(manifest,line))return 184;
        char* end=nullptr;auto count=strtoull(line.c_str(),&end,10);
        if(line.empty()||*end||count<1||count>1000000)return 184;
        expected=(unsigned)count;
    }else if(line!="FM27DW1")return 184;
    FILE* session_log=log_file;unsigned index=0;
    while(std::getline(manifest,line)){
        if(line.empty())continue;desktop_check_cancel();if(++index>expected)return 184;
        std::string fields[5];fields[0]=line;
        for(unsigned i=1;i<5;i++)if(!std::getline(manifest,fields[i]))return 184;
        fixture=fs::u8path(fields[0]);scenario_file=fs::u8path(fields[1]);output=fs::u8path(fields[2]);
        char* end=nullptr;auto seed=strtoull(fields[3].c_str(),&end,10);if(fields[3].empty()||*end||seed>UINT32_MAX)return 184;
        requested_seed=(uint32_t)seed;seed_override=true;dump_input=fields[4]=="-"?fs::path():fs::u8path(fields[4]);
        if(fs::exists(output)||fs::exists(output.wstring()+L".worker_done"))return 187;
        FILE* next=_wfsopen(output.c_str(),L"w",_SH_DENYNO);if(!next)return 98;
        {std::lock_guard<std::recursive_mutex> lock(worker_log_lock);log_file=next;}
        timing_start=GetTickCount64();timing_loaded=timing_active=timing_start;
        scenario_edits.clear();memset(game_constraints,0,sizeof(game_constraints));memset(original_roster,0,sizeof(original_roster));
        input_cursor=input_reads=0;execution_reset_match();
        fprintf(log_file,"{\"event\":\"native_worker_job_started\",\"index\":%u,\"pid\":%lu,\"bootstrap_reused\":%s}\n",index,GetCurrentProcessId(),worker_bootstrapped?"true":"false");fflush(log_file);
        int result=native_match(object);if(result)return result;
        {std::lock_guard<std::recursive_mutex> lock(worker_log_lock);log_file=session_log;}
        if(fclose(next))return 186;
        auto marker=output;marker+=L".worker_done";FILE* ack=nullptr;if(_wfopen_s(&ack,marker.c_str(),L"wb"))return 185;
        fprintf(ack,"{\"index\":%u,\"pid\":%lu,\"released\":true,\"exit_code\":0}\n",index,GetCurrentProcessId());fclose(ack);
    }
    if(counted&&index!=expected)return 184;
    fprintf(log_file,"{\"event\":\"native_worker_completed\",\"jobs\":%u}\n",index);fflush(log_file);return index?0:184;
}

static bool find_activation=false;
static bool read_own(const void* p,void* out,size_t n){SIZE_T got=0;return ReadProcessMemory(GetCurrentProcess(),p,out,n,&got)&&got==n;}
// Diagnostic for a new game build: the host waits for a word in the protected section (.00cfg) to drop
// to 0 once the game's own start-up checks have finished. That section is regenerated per build, so the
// word moves. Watch every 4-aligned word that reads 1 on disk and log those that settle at 0. Read only.
static int scan_activation(HMODULE module,const wchar_t* path){
    auto base=(unsigned char*)module;
    auto nt=(IMAGE_NT_HEADERS64*)(base+((IMAGE_DOS_HEADER*)base)->e_lfanew);
    auto sec=IMAGE_FIRST_SECTION(nt);const IMAGE_SECTION_HEADER* cfg=nullptr;
    for(unsigned i=0;i<nt->FileHeader.NumberOfSections;i++)if(!strncmp((const char*)sec[i].Name,".00cfg",8))cfg=&sec[i];
    if(!cfg){fprintf(log_file,"{\"event\":\"activation_scan_error\",\"reason\":\"no_00cfg\"}\n");fflush(log_file);return 120;}
    CompatImage file;std::vector<unsigned char> disk(cfg->SizeOfRawData);
    if(!file.open(path)||!file.read(cfg->VirtualAddress,disk.data(),disk.size())){fprintf(log_file,"{\"event\":\"activation_scan_error\",\"reason\":\"file_read\"}\n");fflush(log_file);return 121;}
    struct Candidate{uint32_t offset;uint32_t first;int zero_ms;unsigned changes;uint32_t last;};
    std::vector<Candidate> c;
    for(uint32_t o=0;o+4<=disk.size();o+=4)if(*(uint32_t*)(disk.data()+o)==1)c.push_back({o,0,-1,0,0});
    auto t0=GetTickCount64();
    std::vector<unsigned char> page(4096);
    auto poll=[&](bool first){
        size_t current=SIZE_MAX;bool ok=false;
        for(auto& x:c){
            size_t p=x.offset/4096;
            if(p!=current){current=p;ok=read_own(base+cfg->VirtualAddress+p*4096,page.data(),4096);}
            uint32_t v=ok?*(uint32_t*)(page.data()+x.offset%4096):0xffffffffu;
            if(first){x.first=x.last=v;if(!v)x.zero_ms=0;continue;}
            if(v!=x.last){x.changes++;if(!v&&x.zero_ms<0)x.zero_ms=(int)(GetTickCount64()-t0);x.last=v;}
        }
    };
    poll(true);
    fprintf(log_file,"{\"event\":\"activation_scan_started\",\"section_rva\":\"0x%lx\",\"disk_ones\":%zu}\n",cfg->VirtualAddress,c.size());fflush(log_file);
    while(GetTickCount64()-t0<20000){Sleep(100);poll(false);}
    unsigned listed=0,already=0;
    for(auto& x:c){
        if(x.last)continue;
        if(x.first==0){if(++already>50)continue;}
        else if(++listed>200)continue;
        char context[65]={};
        for(unsigned i=0;i<32&&x.offset+i<disk.size();i++)sprintf_s(context+2*i,3,"%02x",disk[x.offset+i]);
        fprintf(log_file,"{\"event\":\"activation_candidate\",\"rva\":\"0x%lx\",\"at_load\":%u,\"zero_ms\":%d,\"changes\":%u,\"aligned8\":%s,\"disk\":\"%s\"}\n",
            (unsigned long)(cfg->VirtualAddress+x.offset),x.first,x.zero_ms,x.changes,x.offset%8?"false":"true",context);
    }
    fprintf(log_file,"{\"event\":\"activation_scan_completed\",\"turned_zero_after_load\":%u,\"already_zero_at_load\":%u}\n",listed,already);fflush(log_file);
    // After 20 s the game's start-up is long finished: check that the engine interface comes up.
    unsigned char object[0x48]={};
    auto result=((void*(*)(void*))(base+0x4ba21d0))(object);
    fprintf(log_file,"{\"event\":\"native_interface_created\",\"self_returned\":%s,\"vtable_rva\":\"0x%llx\"}\n",result==object?"true":"false",*(unsigned long long*)object-(unsigned long long)base);fflush(log_file);
    return 0;
}

static int child(bool run_match){
    timing_start=GetTickCount64();
    SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOGPFAULTERRORBOX|SEM_NOOPENFILEERRORBOX);
    log_file=_wfsopen(output.c_str(),L"w",_SH_DENYNO);
    if(!log_file)return 98;
    AddVectoredExceptionHandler(0,observe);
    wchar_t desktop[256]={};DWORD needed=0;
    GetUserObjectInformationW(GetThreadDesktop(GetCurrentThreadId()),UOI_NAME,desktop,sizeof(desktop),&needed);
    fprintf(log_file,"{\"event\":\"simulator_started\",\"isolated_desktop\":%s,\"full_match_completed\":false,\"extracted_engine\":false}\n",wcsstr(desktop,L"FmEngineControl_")?"true":"false");fflush(log_file);
    if(!wcsstr(desktop,L"FmEngineControl_"))return 80;
    wchar_t libs[MAX_PATH],image[MAX_PATH];
    wcscpy_s(libs,(desktop_game_root.empty()?bundle/L"libs":desktop_game_root/L"fm_Data/Plugins/x86_64").c_str());
    wcscpy_s(image,(desktop_game_root.empty()?bundle/L"game_plugin.dll":desktop_game_root/L"fm_Data/Plugins/x86_64/game_plugin.dll").c_str());
    if(!known_image(image)){fprintf(log_file,"{\"event\":\"unsupported_engine_compatibility\"}\n");fflush(log_file);return 99;}
    SetEnvironmentVariableW(L"SteamNoOverlayUI",L"1");
    fprintf(log_file,"{\"event\":\"headless_steam_policy\",\"overlay_ui_disabled\":true}\n");fflush(log_file);
    // Installation app manifest metadata, not a fabricated ownership response.
    SetEnvironmentVariableW(L"SteamAppId",L"4530370");
    SetEnvironmentVariableW(L"SteamGameId",L"4530370");
    SetDefaultDllDirectories(LOAD_LIBRARY_SEARCH_SYSTEM32|LOAD_LIBRARY_SEARCH_USER_DIRS);
    AddDllDirectory(libs);
    fprintf(log_file,"{\"event\":\"windows_load_started\"}\n");fflush(log_file);
    auto module=LoadLibraryExW(image,nullptr,LOAD_LIBRARY_SEARCH_DLL_LOAD_DIR|LOAD_LIBRARY_SEARCH_SYSTEM32|LOAD_LIBRARY_SEARCH_USER_DIRS);
    fprintf(log_file,"{\"event\":\"windows_load_returned\",\"success\":%s,\"error\":%lu}\n",module?"true":"false",GetLastError());fflush(log_file);
    if(!module)return 81;
    native_base=(unsigned char*)module;
    timing_loaded=GetTickCount64();
    bool game_runtime_absent=!GetModuleHandleW(L"fm.exe")&&!GetModuleHandleW(L"UnityPlayer.dll")&&!GetModuleHandleW(L"GameAssembly.dll");
    fprintf(log_file,"{\"event\":\"runtime_dependencies_checked\",\"fm_exe_unity_player_game_assembly_absent\":%s}\n",game_runtime_absent?"true":"false");fflush(log_file);
    if(!game_runtime_absent)return 100;
    if(policy_audit)return audit_policies();
    if(find_activation)return scan_activation(module,image);
    if(!compat_activation_flag){fprintf(log_file,"{\"event\":\"activation_flag_unmapped\"}\n");fflush(log_file);return 82;}
    auto flag=(volatile unsigned int*)((unsigned char*)module+compat_activation_flag);
    for(unsigned i=0;i<100;i++){
        if(*flag==0){
            desktop_check_cancel();
            timing_active=GetTickCount64();
            fprintf(log_file,"{\"event\":\"native_activation_completed\"}\n");fflush(log_file);
            unsigned char object[0x48]={};
            auto result=((void*(*)(void*))((unsigned char*)module+0x4ba21d0))(object);
            fprintf(log_file,"{\"event\":\"native_interface_created\",\"self_returned\":%s,\"vtable_rva\":\"0x%llx\"}\n",result==object?"true":"false",*(unsigned long long*)object-(unsigned long long)module);fflush(log_file);
            if(run_match)return worker_manifest.empty()?native_match(object):worker_loop(object);
            return 0;
        }
        Sleep(100);
    }
    fprintf(log_file,"{\"event\":\"activation_still_pending\",\"word\":%u}\n",*flag);fflush(log_file);return 82;
}
int wmain(int argc,wchar_t** argv){
    wchar_t executable[MAX_PATH];GetModuleFileNameW(nullptr,executable,MAX_PATH);bundle=fs::path(executable).parent_path();
    wchar_t desktop_env[32768]={};
    if(GetEnvironmentVariableW(L"FM27_ENGINE_ROOT",desktop_env,32768))bundle=fs::path(desktop_env)/L"fm27_native";
    if(GetEnvironmentVariableW(L"FM27_GAME_ROOT",desktop_env,32768))desktop_game_root=desktop_env;
    fixture=bundle/L"fixtures/match.pkm";output=bundle/L"last_match.jsonl";
    fs::path check_image;
    bool is_child=false;
    for(int i=1;i<argc;i++){
        std::wstring arg=argv[i];
        if(arg==L"--check-image"&&i+1<argc)check_image=fs::absolute(argv[++i]);
        else if(arg==L"--inspect-fixture")inspect_fixture_only=true;
        else if(arg==L"--worker-capabilities"){puts("{\"protocol\":2,\"max_jobs\":1000000,\"execution_context_reset\":true,\"per_match_resource_release\":true}");return 0;}
        else if(arg==L"--worker-manifest"&&i+1<argc)worker_manifest=fs::absolute(argv[++i]);
        else if(arg==L"--cancel-event"&&i+1<argc)desktop_cancel_name=argv[++i];
        else if(arg==L"--child")is_child=true;
        else if(arg==L"--policy-audit")policy_audit=true;
        else if(arg==L"--find-activation")find_activation=true;
        else if(arg==L"--match"){}
        else if(arg==L"--help"){puts("FM27Simulator [--fixture INPUT.pkm] [--seed UINT32] [--output RUN.jsonl] [--tick-step 1..256]\nRuns original native simulation on a private desktop. Retains the complete native DLL; no fm.exe or Unity launch.");return 0;}
        else if((arg==L"--fixture"||arg==L"--output"||arg==L"--seed"||arg==L"--tick-step"||arg==L"--dump-input"||arg==L"--scenario-file")&&i+1<argc){
            auto value=argv[++i];
            if(arg==L"--fixture")fixture=fs::absolute(value);
            else if(arg==L"--output")output=fs::absolute(value);
            else if(arg==L"--dump-input")dump_input=fs::absolute(value);
            else if(arg==L"--scenario-file")scenario_file=fs::absolute(value);
            else{
                wchar_t* end=nullptr;auto n=wcstoull(value,&end,10);
                if(!*value||*value==L'-'||*end||n>UINT32_MAX){fputs("Invalid numeric argument\n",stderr);return 79;}
                if(arg==L"--seed"){seed_override=true;requested_seed=(uint32_t)n;}
                else if(n>=1&&n<=256)tick_step=(int)n;
                else return 79;
            }
        }else{fputs("Unknown or incomplete argument\n",stderr);return 79;}
    }
    if(!check_image.empty()){log_file=stdout;return known_image(check_image)?0:99;}
    if(!desktop_cancel_name.empty()){desktop_cancel_event=OpenEventW(SYNCHRONIZE|EVENT_MODIFY_STATE,FALSE,desktop_cancel_name.c_str());if(!desktop_cancel_event)return 181;}
    if(is_child){unsigned status=child(true);desktop_finish_and_exit(status);}
    wchar_t desktop_name[96];swprintf_s(desktop_name,L"FmEngineControl_%lu",GetCurrentProcessId());
    auto desktop=CreateDesktopW(desktop_name,nullptr,nullptr,0,GENERIC_ALL,nullptr);
    if(!desktop){printf("desktop_create_error=%lu\n",GetLastError());return 83;}
    auto quote=[](const std::wstring& s){std::wstring q=L"\"";size_t slashes=0;for(auto c:s){if(c==L'\\'){slashes++;continue;}if(c==L'\"')q.append(slashes*2+1,L'\\');else q.append(slashes,L'\\');slashes=0;q+=c;}q.append(slashes*2,L'\\');return q+L'\"';};
    std::wstring command=quote(executable)+L" --child --fixture "+quote(fixture.wstring())+L" --output "+quote(output.wstring())+L" --tick-step "+std::to_wstring(tick_step);
    if(!worker_manifest.empty())command+=L" --worker-manifest "+quote(worker_manifest.wstring());
    if(seed_override)command+=L" --seed "+std::to_wstring(requested_seed);
    if(policy_audit)command+=L" --policy-audit";
    if(find_activation)command+=L" --find-activation";
    if(!desktop_cancel_name.empty())command+=L" --cancel-event "+quote(desktop_cancel_name);
    if(!dump_input.empty())command+=L" --dump-input "+quote(dump_input.wstring());
    if(inspect_fixture_only)command+=L" --inspect-fixture";
    if(!scenario_file.empty())command+=L" --scenario-file "+quote(scenario_file.wstring());
    STARTUPINFOW start={};start.cb=sizeof(start);start.lpDesktop=desktop_name;
    PROCESS_INFORMATION process={};
    HANDLE job=CreateJobObjectW(nullptr,nullptr);
    JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits={};
    limits.BasicLimitInformation.LimitFlags=JOB_OBJECT_LIMIT_ACTIVE_PROCESS|JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
    limits.BasicLimitInformation.ActiveProcessLimit=1;
    if(!job||!SetInformationJobObject(job,JobObjectExtendedLimitInformation,&limits,sizeof(limits))){if(job)CloseHandle(job);CloseDesktop(desktop);return 101;}
    if(!CreateProcessW(executable,command.data(),nullptr,nullptr,FALSE,CREATE_NO_WINDOW|CREATE_SUSPENDED,nullptr,nullptr,&start,&process)){
        printf("child_start_error=%lu\n",GetLastError());CloseDesktop(desktop);return 84;
    }
    if(!AssignProcessToJobObject(job,process.hProcess)){
        auto error=GetLastError();TerminateProcess(process.hProcess,102);CloseHandle(process.hThread);CloseHandle(process.hProcess);CloseHandle(job);CloseDesktop(desktop);printf("process_isolation_error=%lu\n",error);return 102;
    }
    ResumeThread(process.hThread);
    DWORD worker_wait=180000u;
    if(!worker_manifest.empty()){
        std::ifstream manifest(worker_manifest);std::string magic;std::getline(manifest,magic);
        // Python enforces each match's progress and cancellation deadlines.
        worker_wait=magic=="FM27DW2"?INFINITE:64u*180000u;
    }
    if(WaitForSingleObject(process.hProcess,worker_wait)==WAIT_TIMEOUT){if(desktop_cancel_event)SetEvent(desktop_cancel_event);if(!desktop_cancel_event||WaitForSingleObject(process.hProcess,15000)==WAIT_TIMEOUT){printf("steam_cleanup_timeout_forced_termination=1\n");TerminateProcess(process.hProcess,85);WaitForSingleObject(process.hProcess,3000);}}
    DWORD code=0;GetExitCodeProcess(process.hProcess,&code);
    printf("native_match_exit=%lu\n",code);
    CloseHandle(process.hThread);CloseHandle(process.hProcess);CloseHandle(job);CloseDesktop(desktop);
    return (int)code;
}
