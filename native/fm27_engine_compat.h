// Validate the adapter contract, not a whole-file SHA whitelist.
#include <map>
#include <cctype>
#include "engine_compat_profile.h"
struct CompatImage {
    std::ifstream file;uint64_t size=0;IMAGE_NT_HEADERS64 nt={};std::vector<IMAGE_SECTION_HEADER> sections;
    bool raw(uint64_t offset,void* out,size_t n){if(offset>size||n>size-offset)return false;file.clear();file.seekg(offset);file.read((char*)out,n);return(bool)file;}
    bool open(const fs::path& path){
        file.open(path,std::ios::binary);if(!file)return false;file.seekg(0,std::ios::end);size=(uint64_t)file.tellg();IMAGE_DOS_HEADER dos={};
        if(!raw(0,&dos,sizeof(dos))||dos.e_magic!=IMAGE_DOS_SIGNATURE||dos.e_lfanew<0||!raw(dos.e_lfanew,&nt,sizeof(nt)))return false;
        if(nt.Signature!=IMAGE_NT_SIGNATURE||nt.FileHeader.Machine!=IMAGE_FILE_MACHINE_AMD64||nt.OptionalHeader.Magic!=IMAGE_NT_OPTIONAL_HDR64_MAGIC||nt.FileHeader.NumberOfSections>96||nt.FileHeader.SizeOfOptionalHeader<sizeof(IMAGE_OPTIONAL_HEADER64))return false;
        sections.resize(nt.FileHeader.NumberOfSections);return raw((uint64_t)dos.e_lfanew+24+nt.FileHeader.SizeOfOptionalHeader,sections.data(),sections.size()*sizeof(IMAGE_SECTION_HEADER));
    }
    bool mapped(uint64_t rva,size_t n){for(auto& s:sections)if(rva>=s.VirtualAddress&&rva+n<=(uint64_t)s.VirtualAddress+std::max(s.Misc.VirtualSize,s.SizeOfRawData))return true;return false;}
    bool read(uint64_t rva,void* out,size_t n){
        if(rva<nt.OptionalHeader.SizeOfHeaders)return raw(rva,out,n);
        for(auto& s:sections)if(rva>=s.VirtualAddress&&rva+n<=(uint64_t)s.VirtualAddress+s.SizeOfRawData)return raw((uint64_t)s.PointerToRawData+rva-s.VirtualAddress,out,n);
        return false;
    }
    bool text(uint64_t rva,std::string& value){value.clear();for(unsigned i=0;i<1024;i++){char c=0;if(!read(rva+i,&c,1))return false;if(!c)return true;value+=c;}return false;}
};
static bool compatible_image(const fs::path& path){
    CompatImage image;const char* error=nullptr;unsigned failed_rva=0,warnings=0;
    if(!image.open(path))error="invalid_PE_or_architecture";
    else if(image.nt.OptionalHeader.ImageBase!=compat_image_base||image.nt.OptionalHeader.AddressOfEntryPoint!=compat_entrypoint||image.nt.OptionalHeader.SizeOfImage<compat_minimum_image)error="PE_layout";
    if(!error)for(auto expected:compat_sections){bool found=false;for(auto& s:image.sections)if(s.VirtualAddress==expected.rva&&(s.Characteristics&0xe0000000u)==expected.flags)found=true;if(!found){error="section_layout";failed_rva=expected.rva;break;}}
    if(!error)for(auto expected:compat_data)if(!image.mapped(expected.rva,expected.size)){error="data_bounds";failed_rva=expected.rva;break;}
    if(!error)for(auto expected:compat_ranges){
        std::vector<unsigned char> actual(expected.size);
        if(!image.read(expected.rva,actual.data(),actual.size())){error="critical_range_unreadable";failed_rva=expected.rva;break;}
        if(!memcmp(actual.data(),expected.bytes,actual.size()))continue;
        bool executable=false;
        for(auto& s:image.sections)if(expected.rva>=s.VirtualAddress&&(uint64_t)expected.rva+expected.size<=(uint64_t)s.VirtualAddress+s.SizeOfRawData&&(s.Characteristics&IMAGE_SCN_MEM_EXECUTE))executable=true;
        // A stable entry and PE contract permit an isolated trial, not a claim
        // of ABI or behavioral equivalence. Vtable and entry changes stay fatal.
        if(!executable||expected.size<=32||memcmp(actual.data(),expected.bytes,32)){
            error=executable?"critical_entry_signature":"critical_vtable_signature";failed_rva=expected.rva;break;
        }
        warnings++;
        fprintf(log_file,"{\"event\":\"native_engine_compatibility_warning\",\"reason\":\"function_body_unverified\",\"rva\":%u}\n",expected.rva);
    }
    if(!error){
        IMAGE_TLS_DIRECTORY64 tls={};auto d=image.nt.OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_TLS];
        if(!image.read(d.VirtualAddress,&tls,sizeof(tls))||tls.StartAddressOfRawData-compat_image_base!=compat_tls_values[0]||tls.EndAddressOfRawData-tls.StartAddressOfRawData!=compat_tls_values[1]||tls.AddressOfIndex-compat_image_base!=compat_tls_values[2]||tls.SizeOfZeroFill!=compat_tls_values[3])error="TLS_layout";
        else{unsigned i=0;for(auto expected:compat_tls_callbacks){uint64_t actual=0;if(!image.read(tls.AddressOfCallBacks-compat_image_base+8*i++,&actual,8)||actual-compat_image_base!=expected){error="TLS_callback";break;}}uint64_t end=1;if(!error&&(!image.read(tls.AddressOfCallBacks-compat_image_base+8*i,&end,8)||end))error="TLS_callback_count";}
    }
    if(!error){
        std::map<std::string,std::vector<unsigned>> imports;auto d=image.nt.OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT];bool terminated=false;
        for(unsigned i=0;i<8192;i++){
            IMAGE_IMPORT_DESCRIPTOR desc={};if(!image.read(d.VirtualAddress+sizeof(desc)*i,&desc,sizeof(desc))){error="import_table";break;}
            if(!desc.Name&&!desc.FirstThunk){terminated=true;break;}std::string dll;if(!image.text(desc.Name,dll)){error="import_dll_name";break;}
            std::transform(dll.begin(),dll.end(),dll.begin(),[](unsigned char c){return(char)std::tolower(c);});uint64_t source=desc.OriginalFirstThunk?desc.OriginalFirstThunk:desc.FirstThunk;
            bool thunk_terminated=false;for(unsigned j=0;j<32768;j++){
                uint64_t value=0;if(!image.read(source+8*j,&value,8)){error="import_thunk";break;}if(!value){thunk_terminated=true;break;}
                std::string name;if(value&IMAGE_ORDINAL_FLAG64)name="#"+std::to_string(value&0xffff);else if(!image.text(value+2,name)){error="import_function_name";break;}
                imports[dll+"!"+name].push_back(desc.FirstThunk+8*j);
            }if(!error&&!thunk_terminated)error="unterminated_import_thunk";if(error)break;
        }
        if(!error&&!terminated)error="unterminated_import_table";
        if(!error)for(auto expected:compat_imports){auto it=imports.find(std::string(expected.dll)+"!"+expected.name);if(it==imports.end()||std::find(it->second.begin(),it->second.end(),expected.rva)==it->second.end()){error="import_binding";failed_rva=expected.rva;break;}}
    }
    fprintf(log_file,"{\"event\":\"native_engine_compatibility\",\"profile\":\"%s\",\"compatible\":%s,\"trial_allowed\":%s,\"disposition\":\"%s\",\"warning_count\":%u,\"reason\":\"%s\",\"rva\":%u,\"whole_file_hash_is_gate\":false}\n",compat_profile_id,(error||warnings)?"false":"true",(!error&&warnings)?"true":"false",error?"blocked":warnings?"unverified":"verified",warnings,error?error:warnings?"function_body_unverified":"ok",failed_rva);fflush(log_file);return !error;
}
