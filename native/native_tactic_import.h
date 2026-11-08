// The original TAC plan parser consumes a bounded, read-only memory stream.
struct DesktopTacticStream {void** methods;uint64_t reserved;uint32_t error,padding;const unsigned char* data;size_t size,cursor;};
static void* desktop_tac_read(void* self,void* output,size_t n){auto s=(DesktopTacticStream*)self;if(n>s->size||s->cursor>s->size-n){s->error=1;return self;}memcpy(output,s->data+s->cursor,n);s->cursor+=n;return self;}
static uint64_t desktop_tac_tell(void* self){return((DesktopTacticStream*)self)->cursor;}
static void* desktop_tac_seek(void* self,void* result,uint64_t position){auto s=(DesktopTacticStream*)self;if(position>s->size)s->error=1;else s->cursor=(size_t)position;*(uint64_t*)result=0;return result;}
static void desktop_import_tac(unsigned char* match){
    if(desktop_fmf_routine_type>=0)return;
    wchar_t path[32768]={};bool direct=GetEnvironmentVariableW(L"FM27_IMPORT_TAC",path,32768)!=0;if(!direct&&desktop_fmf_payload.empty())return;
    std::vector<unsigned char> bytes=desktop_fmf_payload;if(direct){std::ifstream file(path,std::ios::binary);bytes.assign((std::istreambuf_iterator<char>(file)),{});}if(bytes.size()<8||bytes.size()>1024*1024)TerminateProcess(GetCurrentProcess(),172);
    void* methods[8]={};methods[2]=(void*)desktop_tac_tell;methods[3]=(void*)desktop_tac_seek;methods[5]=(void*)desktop_tac_read;DesktopTacticStream reader={methods,0,0,0,bytes.data(),bytes.size(),0};void* reference=&reader;
    auto team=*(unsigned char**)(match+0x15380);auto manager=*(unsigned char**)(team+0x630);auto accepted=((unsigned char(*)(void*,void**,unsigned char))at(0x16fca0))(manager+0x1818,&reference,1);
    fprintf(log_file,"{\"event\":\"native_tactic_file_parsed\",\"accepted\":%s,\"stream_error\":%u,\"consumed\":%llu,\"size\":%llu,\"mentality\":%u,\"team_bits\":\"",accepted?"true":"false",reader.error,(unsigned long long)reader.cursor,(unsigned long long)reader.size,manager[0x191d]);for(unsigned j=0;j<16;j++)fprintf(log_file,"%02x",manager[0x18f8+j]);fputs("\",\"mapping\":[",log_file);for(unsigned j=0;j<11;j++)fprintf(log_file,"%s%u",j?",":"",manager[0x1fb4+j]);fputs("],\"phases\":[",log_file);
    for(unsigned phase=0;phase<2;phase++){
        fprintf(log_file,"%s[",phase?",":"");for(unsigned i=0;i<11;i++){
            auto cell=manager+(phase?0x1c50:0x1930)+i*0x48;auto pi=instruction_entry(cell,false);fprintf(log_file,"%s{\"position\":%u,\"role_flags\":\"%llu\",\"pi_flags\":\"%llu\",\"target_player\":%u,\"target_position\":%u}",i?",":"",*(unsigned*)cell,(unsigned long long)*(uint64_t*)(cell+0x40),pi?(unsigned long long)pi[1]:0,pi?((unsigned char*)pi)[20]:255,pi?*(uint32_t*)((unsigned char*)pi+16):0);
        }fputs("]",log_file);
    }fputs("]}\n",log_file);fflush(log_file);bool tail=reader.cursor==reader.size||(reader.size-reader.cursor==8&&std::all_of(bytes.begin()+reader.cursor,bytes.end(),[](unsigned char c){return c==0;}));TerminateProcess(GetCurrentProcess(),accepted&&!reader.error&&tail?0:173);
}
