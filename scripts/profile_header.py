"""Render a locally generated adapter contract as a C++ header."""
import json

def header(profile):
    lines = ['#pragma once', 'static const char* compat_profile_id=' + json.dumps(profile['id']) + ';', 'struct CompatRange {unsigned rva,size;const unsigned char* bytes;};']
    for i, r in enumerate(profile['ranges']):
        lines.append('static const unsigned char compat_bytes_' + str(i) + '[]={' + ','.join(('0x' + r['hex'][j:j + 2] for j in range(0, len(r['hex']), 2))) + '};')
    lines.append('static const CompatRange compat_ranges[]={' + ','.join(('{' + str(r['rva']) + ',' + str(len(r['hex']) // 2) + ',compat_bytes_' + str(i) + '}' for i, r in enumerate(profile['ranges']))) + '};')
    lines += ['struct CompatSection {unsigned rva,flags;};', 'static const CompatSection compat_sections[]={' + ','.join(('{' + str(s['rva']) + ',' + str(s['memory_flags']) + 'u}' for s in profile['sections'])) + '};', 'struct CompatData {unsigned rva,size;};', 'static const CompatData compat_data[]={' + ','.join(('{' + str(s['rva']) + ',' + str(s['size']) + '}' for s in profile['data_addresses'])) + '};', 'struct CompatImport {const char* dll;const char* name;unsigned rva;};', 'static const CompatImport compat_imports[]={' + ','.join(('{' + json.dumps(i['dll']) + ',' + json.dumps(i['name']) + ',' + str(i['rva']) + '}' for i in profile['imports'])) + '};', 'static const unsigned long long compat_image_base=' + str(profile['image_base']) + 'ULL;', 'static const unsigned compat_entrypoint=' + str(profile['entrypoint_rva']) + 'u,compat_minimum_image=' + str(profile['minimum_image_size']) + 'u;', 'static const unsigned long long compat_tls_values[]={' + ','.join((str(v) + 'ULL' for v in profile['tls'].values())) + '};', 'static const unsigned long long compat_tls_callbacks[]={' + ','.join((str(v) + 'ULL' for v in profile['tls_callbacks'])) + '};']
    return '\n'.join(lines) + '\n'
