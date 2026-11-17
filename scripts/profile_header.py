"""Render a locally generated adapter contract as a C++ header."""
import json

def header(profile, *, digest_ranges=False):
    lines = ['#pragma once', 'static const char* compat_profile_id=' + json.dumps(profile['id']) + ';']
    if digest_ranges:
        lines.append('#define FM27_COMPAT_DIGEST_RANGES')
        lines.append('static const char* epic_reference_sha256=' + json.dumps(profile['reference_sha256']) + ';')
        lines.append('struct CompatRange {unsigned rva,size;const char* sha256;};')
        ranges = ['{' + str(r['rva']) + ',' + str(r['size']) + ',' + json.dumps(r['sha256']) + '}'
                  for r in profile['ranges']]
    else:
        lines.append('struct CompatRange {unsigned rva,size;const unsigned char* bytes;};')
        ranges = []
        for i, r in enumerate(profile['ranges']):
            name = 'compat_bytes_' + str(i)
            data = bytes.fromhex(r['hex'])
            lines.append('static const unsigned char ' + name + '[]={' + ','.join(hex(b) for b in data) + '};')
            ranges.append('{' + str(r['rva']) + ',' + str(len(data)) + ',' + name + '}')
    lines.append('static const CompatRange compat_ranges[]={' + ','.join(ranges) + '};')
    lines += ['struct CompatSection {unsigned rva,flags;};', 'static const CompatSection compat_sections[]={' + ','.join(('{' + str(s['rva']) + ',' + str(s['memory_flags']) + 'u}' for s in profile['sections'])) + '};', 'struct CompatData {unsigned rva,size;};', 'static const CompatData compat_data[]={' + ','.join(('{' + str(s['rva']) + ',' + str(s['size']) + '}' for s in profile['data_addresses'])) + '};', 'struct CompatImport {const char* dll;const char* name;unsigned rva;};', 'static const CompatImport compat_imports[]={' + ','.join(('{' + json.dumps(i['dll']) + ',' + json.dumps(i['name']) + ',' + str(i['rva']) + '}' for i in profile['imports'])) + '};', 'static const unsigned long long compat_image_base=' + str(profile['image_base']) + 'ULL;', 'static const unsigned compat_entrypoint=' + str(profile['entrypoint_rva']) + 'u,compat_minimum_image=' + str(profile['minimum_image_size']) + 'u;', 'static const unsigned long long compat_tls_values[]={' + ','.join((str(v) + 'ULL' for v in profile['tls'].values())) + '};', 'static const unsigned long long compat_tls_callbacks[]={' + ','.join((str(v) + 'ULL' for v in profile['tls_callbacks'])) + '};', '// 0 = not located yet for this build (FM27Simulator.exe --find-activation).', 'static const unsigned compat_activation_flag=' + str(profile.get('activation_flag_rva') or 0) + 'u;']
    return '\n'.join(lines) + '\n'
