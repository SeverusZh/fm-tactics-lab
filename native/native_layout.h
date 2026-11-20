#pragma once

#include <cstdint>

#include "fm27_adapter_profile.h"

// Object offsets and reference RVAs for the installed build. A runtime profile
// supplies the deltas; without an active profile the compiled-in reference layout
// and RVAs remain in force.
namespace native_layout {

inline bool steam_27_1() {
    return adapter_profile.active && adapter_profile.layout_steam_27_1;
}

inline uintptr_t rva(uintptr_t value) {
    if (!adapter_profile.active) return value;
    auto entry = adapter_profile.rva_map.find((unsigned)value);
    return entry == adapter_profile.rva_map.end() ? value : entry->second;
}

inline unsigned manager(unsigned offset) {
    return offset + (steam_27_1() ? adapter_profile.layout_manager : 0u);
}

inline unsigned player_input(unsigned offset) {
    return offset + (steam_27_1() ? adapter_profile.layout_player_input : 0u);
}

inline unsigned player_runtime(unsigned offset) {
    return offset + (steam_27_1() ? adapter_profile.layout_player_runtime : 0u);
}

inline unsigned player_statistics(unsigned offset) {
    return offset + (steam_27_1() ? adapter_profile.layout_player_statistics : 0u);
}

inline unsigned tactic_version() {
    return steam_27_1() && adapter_profile.layout_tactic_version
        ? adapter_profile.layout_tactic_version
        : 0x1b000000u;
}

inline unsigned execution_sample_stack() {
    return steam_27_1() && adapter_profile.layout_execution_sample_stack
        ? adapter_profile.layout_execution_sample_stack
        : 0x88u;
}

}
