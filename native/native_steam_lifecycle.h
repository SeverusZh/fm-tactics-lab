// Only the current match process's official Steamworks session is released.
// Never unload the game module or change another process's Steam connection.
#pragma once
static HANDLE desktop_cancel_event=nullptr;
static std::wstring desktop_cancel_name;
static LONG desktop_steam_cleanup_started=0;
static bool desktop_steam_cleanup_ok=true;

static bool desktop_steam_cleanup(){
    if(InterlockedCompareExchange(&desktop_steam_cleanup_started,1,0))return desktop_steam_cleanup_ok;
    auto steam=GetModuleHandleW(L"steam_api64.dll");
    if(!steam){if(log_file){fputs("{\"event\":\"steam_session_cleanup\",\"module_loaded\":false,\"ok\":true}\n",log_file);fflush(log_file);}return true;}
    auto shutdown=(void(*)())GetProcAddress(steam,"SteamAPI_Shutdown");
    auto pipe=(int(*)())GetProcAddress(steam,"SteamAPI_GetHSteamPipe");
    auto user=(int(*)())GetProcAddress(steam,"SteamAPI_GetHSteamUser");
    auto release=(void(*)())GetProcAddress(steam,"SteamAPI_ReleaseCurrentThreadMemory");
    int before_pipe=-1,before_user=-1,after_pipe=-1,after_user=-1;DWORD fault=0;
    bool called=false;
    // No C++ stack objects here: this boundary contains an SDK shutdown fault.
    __try{
        if(pipe)before_pipe=pipe();if(user)before_user=user();
        if(release)release();
        if(shutdown){shutdown();called=true;}
        if(pipe)after_pipe=pipe();if(user)after_user=user();
    }__except(EXCEPTION_EXECUTE_HANDLER){fault=GetExceptionCode();}
    desktop_steam_cleanup_ok=called&&!fault&&pipe&&user&&after_pipe==0&&after_user==0;
    if(log_file){fprintf(log_file,"{\"event\":\"steam_session_cleanup\",\"module_loaded\":true,\"shutdown_called\":%s,\"pipe_before\":%d,\"pipe_after\":%d,\"user_before\":%d,\"user_after\":%d,\"fault\":%lu,\"ok\":%s}\n",called?"true":"false",before_pipe,after_pipe,before_user,after_user,fault,desktop_steam_cleanup_ok?"true":"false");fflush(log_file);}
    return desktop_steam_cleanup_ok;
}
[[noreturn]] static void desktop_finish_and_exit(unsigned code){
    if(!desktop_steam_cleanup()&&!code)code=180;
    if(desktop_cancel_event){CloseHandle(desktop_cancel_event);desktop_cancel_event=nullptr;}
    if(log_file){fflush(log_file);FlushFileBuffers((HANDLE)_get_osfhandle(_fileno(log_file)));}
    // Leave native_match's stack-owned buffers alive through DLL detach. Returning
    // from native_match would destroy them too early; TerminateProcess would skip
    // steamclient's process-detach cleanup, including its non-SteamAPI pipes.
    if(log_file){fputs("{\"event\":\"host_orderly_exit_requested\",\"stack_unwound\":false,\"dll_detach_enabled\":true}\n",log_file);fflush(log_file);}
    ExitProcess(code);
    for(;;)Sleep(INFINITE);
}
static void desktop_check_cancel(){
    if(desktop_cancel_event&&WaitForSingleObject(desktop_cancel_event,0)==WAIT_OBJECT_0){
        if(log_file){fputs("{\"event\":\"native_match_cancelled\",\"full_match_completed\":false}\n",log_file);fflush(log_file);}
        desktop_finish_and_exit(86);
    }
}
