// Runtime adapter profile for a game build whose code layout differs from the
// compiled-in reference. The host still owns the call contract; this file only
// relocates the reference RVAs to the installed image and binds the profile to
// one image hash.
#pragma once
#include <map>
#include <string>
#include <fstream>
#include <sstream>
#include <filesystem>
#include <cstdlib>
#include <climits>

struct AdapterProfile {
    bool loaded = false;
    bool allow_partial = false;
    unsigned missing = 0;
    std::string image_sha256;
    std::string reference_id;
    unsigned activation_rva = 0;
    std::map<unsigned, unsigned> rva_map;
    std::string error;
    std::wstring path;
};

static AdapterProfile adapter_profile;

static bool adapter_hex(const std::string& text, unsigned& value) {
    std::string digits = text;
    if (digits.size() > 2 && digits[0] == '0' && (digits[1] == 'x' || digits[1] == 'X')) digits.erase(0, 2);
    if (digits.empty() || digits.size() > 10) return false;
    unsigned long long parsed = 0;
    for (char c : digits) {
        unsigned digit = 0;
        if (c >= '0' && c <= '9') digit = (unsigned)(c - '0');
        else if (c >= 'a' && c <= 'f') digit = (unsigned)(c - 'a' + 10);
        else if (c >= 'A' && c <= 'F') digit = (unsigned)(c - 'A' + 10);
        else return false;
        parsed = parsed * 16 + digit;
    }
    if (parsed > 0xffffffffULL) return false;
    value = (unsigned)parsed;
    return true;
}

static bool adapter_sha(const std::string& text) {
    if (text.size() != 64) return false;
    for (char c : text) {
        if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F'))) return false;
    }
    return true;
}

static bool load_adapter_profile(const std::filesystem::path& bundle) {
    if (adapter_profile.loaded) return adapter_profile.error.empty();
    std::filesystem::path chosen;
    wchar_t environment[32768] = {};
    if (GetEnvironmentVariableW(L"FM27_ADAPTER_PROFILE", environment, 32768)) chosen = environment;
    else {
        auto candidate = bundle / L"adapter_profile.txt";
        std::error_code code;
        if (std::filesystem::exists(candidate, code)) chosen = candidate;
    }
    if (chosen.empty()) return false;
    adapter_profile.path = chosen.wstring();
    std::ifstream input(chosen);
    if (!input) {
        adapter_profile.loaded = true;
        adapter_profile.error = "unreadable";
        return false;
    }
    bool magic = false;
    std::string line;
    while (std::getline(input, line)) {
        if (!line.empty() && line.back() == '\r') line.pop_back();
        auto comment = line.find('#');
        if (comment != std::string::npos) line.resize(comment);
        std::istringstream row(line);
        std::string key;
        if (!(row >> key)) continue;
        if (!magic) {
            std::string version;
            if (key != "fm27-adapter-profile" || !(row >> version) || version != "1") {
                adapter_profile.error = "header";
                break;
            }
            magic = true;
            continue;
        }
        if (key == "image") {
            if (!(row >> adapter_profile.image_sha256)) { adapter_profile.error = "image"; break; }
        } else if (key == "reference") {
            if (!(row >> adapter_profile.reference_id)) { adapter_profile.error = "reference"; break; }
        } else if (key == "activation") {
            std::string value;
            if (!(row >> value) || !adapter_hex(value, adapter_profile.activation_rva)) {
                adapter_profile.error = "activation";
                break;
            }
        } else if (key == "partial") {
            std::string value;
            if (!(row >> value) || (value != "0" && value != "1")) { adapter_profile.error = "partial"; break; }
            adapter_profile.allow_partial = value == "1";
        } else if (key == "missing") {
            std::string value;
            if (!(row >> value)) { adapter_profile.error = "missing"; break; }
            char* end = nullptr;
            unsigned long parsed = std::strtoul(value.c_str(), &end, 10);
            if (value.empty() || *end || parsed > UINT_MAX) { adapter_profile.error = "missing"; break; }
            adapter_profile.missing = (unsigned)parsed;
        } else if (key == "map") {
            std::string source, target;
            unsigned from = 0, to = 0;
            if (!(row >> source >> target) || !adapter_hex(source, from) || !adapter_hex(target, to)) {
                adapter_profile.error = "map";
                break;
            }
            auto existing = adapter_profile.rva_map.find(from);
            if (existing != adapter_profile.rva_map.end() && existing->second != to) {
                adapter_profile.error = "map_conflict";
                break;
            }
            adapter_profile.rva_map[from] = to;
        } else {
            adapter_profile.error = "unknown_key";
            break;
        }
    }
    if (!magic && adapter_profile.error.empty()) adapter_profile.error = "empty";
    if (adapter_profile.reference_id.empty() && adapter_profile.error.empty()) adapter_profile.error = "reference";
    if (!adapter_sha(adapter_profile.image_sha256) && adapter_profile.error.empty()) adapter_profile.error = "image";
    adapter_profile.loaded = true;
    return adapter_profile.error.empty();
}
