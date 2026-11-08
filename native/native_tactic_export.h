// Original FM27 tactical-plan writer, with a bounded output stream.
struct DesktopTacticWriter {void** methods;uint64_t reserved;uint32_t error,padding;std::vector<unsigned char>* data;size_t cursor;};
static void* desktop_tac_write(void* self,void* source,size_t n){auto w=(DesktopTacticWriter*)self;if(n>4*1024*1024||w->cursor>4*1024*1024-n){w->error=1;return self;}if(w->data->size()<w->cursor+n)w->data->resize(w->cursor+n);memcpy(w->data->data()+w->cursor,source,n);w->cursor+=n;return self;}
static uint64_t desktop_write_tell(void* self){return((DesktopTacticWriter*)self)->cursor;}
static void* desktop_write_seek(void* self,void* result,uint64_t position){auto w=(DesktopTacticWriter*)self;if(position>4*1024*1024)w->error=1;else w->cursor=(size_t)position;*(uint64_t*)result=0;return result;}
static void desktop_export_tac(unsigned char* match){
    wchar_t path[32768]={};if(!GetEnvironmentVariableW(L"FM27_EXPORT_TAC",path,32768))return;wchar_t side_text[8]={};GetEnvironmentVariableW(L"FM27_EXPORT_SIDE",side_text,8);unsigned side=wcstoul(side_text,nullptr,10);if(side>1)TerminateProcess(GetCurrentProcess(),174);
    auto team=*(unsigned char**)(match+0x15380+side*8);auto manager=*(unsigned char**)(team+0x630);auto plan=manager+0x1818;
    wchar_t title[256]={};if(GetEnvironmentVariableW(L"FM27_EXPORT_TITLE",title,256)){auto name=fs::path(title).u8string();((void*(*)(void*,const char*,int))at(0x15a640))(plan+0x778,name.c_str(),-1);}
    std::vector<unsigned char> bytes;void* methods[8]={};methods[2]=(void*)desktop_write_tell;methods[3]=(void*)desktop_write_seek;methods[5]=(void*)desktop_tac_write;DesktopTacticWriter writer={methods,0,0,0,&bytes,0};void* reference=&writer;
    unsigned char accepted=((unsigned char(*)(void*,void**,unsigned char))at(0x49a9ab0))(plan,&reference,1);
    if(accepted&&!writer.error){std::ofstream file(fs::path(path),std::ios::binary);file.write((char*)bytes.data(),bytes.size());file.flush();if(!file)writer.error=1;}
    fprintf(log_file,"{\"event\":\"native_tactic_file_written\",\"accepted\":%s,\"stream_error\":%u,\"size\":%llu,\"side\":%u}\n",accepted?"true":"false",writer.error,(unsigned long long)bytes.size(),side);fflush(log_file);TerminateProcess(GetCurrentProcess(),accepted&&!writer.error?0:175);
}
