import hashlib
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
import desktop_game_db_names

MAGIC=b'\x03\x01tad.'
SCHEMA=3753
EN_NATIONS=(0xff,0xff,None,0x00)
EN_COMPETITIONS=(0xff,0xff,0x00)
ZH_NATIONS=(0x00,0x00,None,0x00)
ZH_COMPETITIONS=(0x00,0x00,0x00)
NATIONS=[(5,['Algeria','Algeria','ALG','Algerian']),
         (40,['São Tomé and Príncipe','São Tomé & Príncipe','STP','São Toméan']),
         (765,['England','England','ENG','English'])]
COMPETITIONS=[(1,['Jupiler Pro League','Jupiler Pro League','JPL']),
              (11,['Premier League','Premier League','PL']),
              (12,['Sky Bet Championship','Championship','CHA'])]
ZH_NATION_NAMES=[(5,['阿尔及利亚','阿尔及利亚','阿尔及','阿尔及利亚']),
                 (40,['圣多美和普林西比','圣普','圣普','圣多美人']),
                 (765,['英格兰','英格兰','英格','英格兰'])]
ZH_COMPETITION_NAMES=[(1,['“Jupiler”比利时足球甲级联赛','“Jupiler”比甲联赛','比甲联']),
                      (11,['英格兰超级联赛','英超联赛','英超']),
                      (12,['英格兰天空博彩冠军联赛','英冠联赛','英冠'])]


def padded(rows,total,prefix):
    filled=list(rows)
    while len(filled)<total:
        index=len(filled)
        filled.append((10000+index,[f'{prefix}{index}',f'{prefix}{index}','XX','X']))
    return filled


def encoded(value,terminator):
    data=value.encode('utf8')
    return struct.pack('<I',len(data))+data+(b'' if terminator is None else bytes([terminator]))


def name_block(records,grammar,count=None):
    body=b''.join(struct.pack('<I',record_id)
                  +b''.join(encoded(value,terminator)for value,terminator in zip(values,grammar))
                  for record_id,values in records)
    return MAGIC+struct.pack('<H',SCHEMA)+struct.pack('<I',len(records)if count is None else count)+body


def name_stream(nations=NATIONS,competitions=COMPETITIONS):
    return (name_block(padded(nations,120,'Nation'),EN_NATIONS)
            +name_block(padded(competitions,600,'League'),EN_COMPETITIONS))


def zh_stream():
    return (name_block(padded(ZH_NATION_NAMES,120,'国家'),ZH_NATIONS)
            +name_block(padded(ZH_COMPETITION_NAMES,600,'联赛'),ZH_COMPETITIONS))


def game_root(folder,version='2700'):
    path=folder/'game'/'shared'/'data'/'database'/'db'/version/(version+'_fm')
    path.mkdir(parents=True)
    (path/'lang_db.dat').write_bytes(b'container-'+version.encode())
    return folder/'game'


def zstd_module():
    return desktop_game_db_names._zstd()


class ParseNameTablesTests(unittest.TestCase):
    def test_returns_only_requested_names(self):
        result=desktop_game_db_names.parse_name_tables(name_stream(),{11,12,999},{5,765})
        self.assertEqual(result['competitions'],{11:'Premier League',12:'Sky Bet Championship'})
        self.assertEqual(result['nations'],{5:'Algeria',765:'England'})
        self.assertEqual(result['language'],'en')

    def test_uses_utf8_byte_lengths(self):
        result=desktop_game_db_names.parse_name_tables(name_stream(),set(),{40})
        self.assertEqual(result['nations'],{40:'São Tomé and Príncipe'})

    def test_empty_requests_return_empty_maps(self):
        result=desktop_game_db_names.parse_name_tables(name_stream(),set(),set())
        self.assertEqual((result['competitions'],result['nations']),({},{}))

    def test_rejects_competition_ids_from_another_table(self):
        with self.assertRaises(ValueError):
            desktop_game_db_names.parse_name_tables(name_stream(),{999999},{5})

    def test_unmatched_nation_ids_leave_nations_empty(self):
        result=desktop_game_db_names.parse_name_tables(name_stream(),{11},{999999})
        self.assertEqual(result['nations'],{})
        self.assertEqual(result['competitions'],{11:'Premier League'})

    def test_rejects_stream_without_name_tables(self):
        with self.assertRaises(ValueError):
            desktop_game_db_names.parse_name_tables(b'not a name table',{1},{1})

    def test_rejects_truncated_second_block(self):
        stream=name_stream()[:-5]
        with self.assertRaises(ValueError):
            desktop_game_db_names.parse_name_tables(stream,{11},{5})


class ChineseNameTablesTests(unittest.TestCase):
    def test_chinese_tables_are_preferred_when_available(self):
        stream=name_stream()+zh_stream()
        result=desktop_game_db_names.parse_name_tables(stream,{11,12},{5,765},language='zh')
        self.assertEqual(result['language'],'zh')
        self.assertEqual(result['competitions'],{11:'英超联赛',12:'英冠联赛'})
        self.assertEqual(result['nations'],{5:'阿尔及利亚',765:'英格兰'})

    def test_missing_chinese_entries_fall_back_to_english(self):
        stream=name_stream()+name_block(padded(ZH_NATION_NAMES,120,'国家'),ZH_NATIONS)
        result=desktop_game_db_names.parse_name_tables(stream,{11},{5},language='zh')
        self.assertEqual(result['language'],'zh')
        self.assertEqual(result['competitions'],{11:'Premier League'})
        self.assertEqual(result['nations'],{5:'阿尔及利亚'})

    def test_english_tables_ignore_chinese_names(self):
        stream=name_stream()+zh_stream()
        result=desktop_game_db_names.parse_name_tables(stream,{11},{5},language='en')
        self.assertEqual(result['competitions'],{11:'Premier League'})
        self.assertEqual(result['nations'],{5:'Algeria'})


class LanguageDatabaseTests(unittest.TestCase):
    def test_finds_highest_numeric_version_with_names_database(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            database=root/'shared/data/database/db'
            for version in ('2600','2700'):
                path=database/version/(version+'_fm')
                path.mkdir(parents=True)
                (path/'lang_db.dat').write_bytes(b'x')
            (database/'2800').mkdir()
            (database/'editor data').mkdir()
            self.assertEqual(desktop_game_db_names._lang_db_path(root),
                database/'2700/2700_fm/lang_db.dat')
            self.assertIsNone(desktop_game_db_names._lang_db_path(root/'missing'))
            self.assertIsNone(desktop_game_db_names._lang_db_path(None))

    def test_cache_key_ignores_set_order_but_not_ids_or_language(self):
        digest='a'*64
        self.assertEqual(desktop_game_db_names._cache_key(digest,{1,2},{3},'en'),
                         desktop_game_db_names._cache_key(digest,{2,1},{3},'en'))
        self.assertNotEqual(desktop_game_db_names._cache_key(digest,{1,2},{3},'en'),
                            desktop_game_db_names._cache_key(digest,{1,3},{3},'en'))
        self.assertNotEqual(desktop_game_db_names._cache_key(digest,{1,2},{3},'en'),
                            desktop_game_db_names._cache_key(digest,{1,2},{3},'zh'))


class FrameDecompressionTests(unittest.TestCase):
    def setUp(self):
        try:
            self.zstd=zstd_module()
        except ImportError:
            self.skipTest('zstd 模块不可用')

    def test_joins_consecutive_frames(self):
        chunks=[b'alpha',b'beta'*100,b'gamma'*3]
        raw=b'\x00'*38+b''.join(self.zstd.compress(chunk)for chunk in chunks)
        self.assertEqual(desktop_game_db_names._decompress_frames(raw,1<<20),b''.join(chunks))

    def test_honours_decompressed_limit(self):
        raw=b''.join(self.zstd.compress(chunk)for chunk in (b'alpha',b'beta'*100))
        self.assertEqual(desktop_game_db_names._decompress_frames(raw,8),b'alphabet')

    def test_skips_garbage_between_frames(self):
        frames=[self.zstd.compress(b'first'),self.zstd.compress(b'second')]
        raw=b'\x00'*38+frames[0]+b'garbage'+frames[1]
        self.assertEqual(desktop_game_db_names._decompress_frames(raw,1<<20),b'firstsecond')


class ResolveTests(unittest.TestCase):
    def test_missing_game_root_is_unavailable(self):
        for root in (None,''):
            with self.subTest(root=root):
                result=desktop_game_db_names.resolve(root,{1},{2})
                self.assertEqual((result['competitions'],result['nations'],result['source']),
                    ({},{},'unavailable'))
                self.assertTrue(result['detail'])

    def test_unreadable_database_falls_back_without_raising(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=game_root(Path(tmp))
            result=desktop_game_db_names.resolve(root,{11},{5},cache_root=Path(tmp)/'data')
            self.assertEqual(result['source'],'unavailable')
            self.assertEqual(result['competitions'],{})
            self.assertEqual(result['nations'],{})
            self.assertTrue(result['detail'])

    def test_resolve_names_and_reuses_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=game_root(Path(tmp))
            stream=name_stream()
            data=Path(tmp)/'data'
            with mock.patch.object(desktop_game_db_names,'_decompress_frames',return_value=stream):
                first=desktop_game_db_names.resolve(root,{11,12},{5},cache_root=data,language='en')
            self.assertEqual(first['source'],'game_db')
            self.assertEqual(first['competitions'],{11:'Premier League',12:'Sky Bet Championship'})
            self.assertEqual(first['nations'],{5:'Algeria'})
            self.assertEqual(first['language'],'en')
            self.assertIn('2700',first['detail'])
            caches=list((data/'game_db_names').glob('*.json'))
            self.assertEqual(len(caches),1)
            self.assertRegex(caches[0].name,r'^[0-9a-f]{16}-[0-9a-f]{16}\.json$')
            self.assertEqual(caches[0].name.split('-')[0],
                hashlib.sha256((root/'shared/data/database/db/2700/2700_fm/lang_db.dat').read_bytes()).hexdigest()[:16])
            with mock.patch.object(desktop_game_db_names,'_decompress_frames',side_effect=AssertionError('cache miss')):
                again=desktop_game_db_names.resolve(root,{11,12},{5},cache_root=data,language='en')
            self.assertEqual(again,first)
            self.assertTrue(all(type(key)is int for key in again['competitions']))

    def test_language_is_part_of_the_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=game_root(Path(tmp))
            data=Path(tmp)/'data'
            with mock.patch.object(desktop_game_db_names,'_decompress_frames',return_value=name_stream()):
                desktop_game_db_names.resolve(root,{11},{5},cache_root=data,language='en')
            with mock.patch.object(desktop_game_db_names,'_decompress_frames',
                    return_value=name_stream()+zh_stream()):
                result=desktop_game_db_names.resolve(root,{11},{5},cache_root=data,language='zh')
            self.assertEqual(result['language'],'zh')
            self.assertEqual(result['competitions'],{11:'英超联赛'})
            self.assertEqual(len(list((data/'game_db_names').glob('*.json'))),2)

    def test_overlap_failure_falls_back_and_writes_no_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=game_root(Path(tmp))
            data=Path(tmp)/'data'
            with mock.patch.object(desktop_game_db_names,'_decompress_frames',return_value=name_stream()):
                result=desktop_game_db_names.resolve(root,{999999},{5},cache_root=data)
            self.assertEqual(result['source'],'unavailable')
            self.assertEqual(result['competitions'],{})
            self.assertEqual(result['nations'],{})
            self.assertIn('名称表',result['detail'])
            self.assertFalse((data/'game_db_names').exists())

    def test_default_cache_root_uses_environment_data_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=game_root(Path(tmp))
            data=Path(tmp)/'data'
            with mock.patch.dict(os.environ,{'FM27_DESKTOP_DATA':str(data)}),\
                 mock.patch.object(desktop_game_db_names,'_decompress_frames',return_value=name_stream()):
                result=desktop_game_db_names.resolve(root,{11},{5})
            self.assertEqual(result['source'],'game_db')
            self.assertEqual(len(list((data/'game_db_names').glob('*.json'))),1)


if __name__=='__main__':
    unittest.main()
