// 2494687 inlines this 24-byte POD vector operation. Retain engine ownership
// of its buffers using the allocation and release paths of its vector routines.
static void formal_release_tactic_buffer(unsigned char* allocator, void* buffer, size_t bytes){
    if(!buffer)return;
    const auto prefix=*reinterpret_cast<unsigned*>(allocator+0x30);
    if(allocator[0x34]==1){
        auto pools=*reinterpret_cast<unsigned char***>(allocator+0x18);
        auto end=*reinterpret_cast<unsigned char***>(allocator+0x20);
        if(bytes<static_cast<size_t>(end-pools)){
            if(auto pool=pools[bytes]){
                auto entry=reinterpret_cast<PSLIST_ENTRY>(static_cast<unsigned char*>(buffer)-*reinterpret_cast<unsigned*>(pool+0x78));
                InterlockedPushEntrySList(reinterpret_cast<PSLIST_HEADER>(pool+0x20),entry);
                const bool last=pool[0x48]!=1||InterlockedDecrement(reinterpret_cast<volatile LONG*>(pool+0x40))==0;
                if(last&&pool[0x61]==1)((void(*)(void*))at(0x4d30))(pool);
                return;
            }
        }
    }
    // Use the same CRT instance as the game allocator.
    (*reinterpret_cast<void(**)(void*)>(at(0x52737c0)))(static_cast<unsigned char*>(buffer)-prefix);
}

static uint64_t* formal_insert_tactic_instruction(unsigned char* cell,uint64_t* position,const uint64_t* value){
    constexpr size_t stride=3*sizeof(uint64_t);
    auto vector=reinterpret_cast<uintptr_t*>(cell+8);
    const auto begin=vector[0],end=vector[1],limit=vector[2],insert=reinterpret_cast<uintptr_t>(position);
    if(begin>insert||insert>end||end>limit||(end-begin)%stride||(limit-begin)%stride||(insert-begin)%stride)
        desktop_finish_and_exit(108);
    const size_t used=end-begin,capacity=limit-begin,offset=insert-begin;
    if(capacity-used>=stride){
        memmove(reinterpret_cast<void*>(insert+stride),position,used-offset);
        memcpy(position,value,stride);
        vector[1]+=stride;
        return position;
    }
    if(capacity>SIZE_MAX/2-stride)desktop_finish_and_exit(108);
    const size_t new_capacity=std::max(used+stride,capacity+(capacity/stride/2)*stride);
    auto allocator=*reinterpret_cast<unsigned char**>(at(0x580eaf0));
    auto next=static_cast<unsigned char*>(((void*(*)(void*,size_t))at(0xc03d0))(allocator,new_capacity));
    if(!next)desktop_finish_and_exit(108);
    if(offset)memcpy(next,reinterpret_cast<void*>(begin),offset);
    memcpy(next+offset,value,stride);
    if(used>offset)memcpy(next+offset+stride,position,used-offset);
    formal_release_tactic_buffer(allocator,reinterpret_cast<void*>(begin),capacity);
    vector[0]=reinterpret_cast<uintptr_t>(next);
    vector[1]=vector[0]+used+stride;
    vector[2]=vector[0]+new_capacity;
    return reinterpret_cast<uint64_t*>(next+offset);
}
