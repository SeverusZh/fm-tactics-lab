static void staff_body_diagnostic(){
    wchar_t path[32768]={};if(!GetEnvironmentVariableW(L"FM27_STAFF_FRAGMENT_DIRECTORY",path,32768))return;
    *(unsigned char*)at(0x58204dc)=0;*(unsigned char*)at(0x5820e62)=0;*(unsigned char*)at(0x5820e63)=1;
    for(auto entry:fs::directory_iterator(fs::path(path))){
        if(entry.path().extension()!=L".bin")continue;
        std::ifstream file(entry.path(),std::ios::binary);std::vector<unsigned char> data((std::istreambuf_iterator<char>(file)),{});
        void* methods[8]={};methods[2]=(void*)desktop_tac_tell;methods[3]=(void*)desktop_tac_seek;methods[5]=(void*)desktop_tac_read;
        DesktopTacticStream stream={methods,0x200000001ULL,0,0,data.data(),data.size(),0};void* reference=&stream;
        auto object=(unsigned char*)calloc(1,0x240);*(void**)object=at(0x4e90848);*(void**)(object+0x100)=at(0x4e908b8);*(void**)(object+0x128)=at(0x4e90868);
        unsigned char schema[0x800]={};*(uint16_t*)(schema+0x720)=4000;
        fprintf(log_file,"{\"event\":\"staff_body_begin\",\"selector\":%s}\n",entry.path().stem().string().c_str());fflush(log_file);
        auto okay=((unsigned char(*)(void*,void**,unsigned char,void*,unsigned,unsigned,unsigned char,void*))at(0x180d030))(object+0x100,&reference,0,schema,1,0,1,nullptr);
        fprintf(log_file,"{\"event\":\"staff_body_read\",\"selector\":%s,\"accepted\":%s,\"error\":%u,\"consumed\":%llu,\"profile_hex\":\"",entry.path().stem().string().c_str(),okay?"true":"false",stream.error,(unsigned long long)stream.cursor);
        for(unsigned i=0;i<52;i++)fprintf(log_file,"%02x",object[0x10+i]);fputs("\",\"native_d4_to_f4_hex\":\"",log_file);
        for(unsigned i=0xd4;i<0xf5;i++)fprintf(log_file,"%02x",object[i]);fputs("\",\"generation_trait_pairs\":[",log_file);
        auto traits=*(unsigned char***)(object+0xa8);unsigned emitted=0;
        if(traits)for(auto p=traits[0];p!=traits[1];p+=2)if(((unsigned char(*)(void*))at(0x30714c0))(p))fprintf(log_file,"%s[%u,%u]",emitted++?",":"",p[0],p[1]);
        fputs("]}\n",log_file);fflush(log_file);
        if(!okay||stream.error)desktop_finish_and_exit(240);
    }
    desktop_finish_and_exit(0);
}
