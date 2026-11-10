"""Portable saved-review index mechanics; no new market replay or approval."""
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import unittest
from dataclasses import replace
from decimal import Inexact, localcontext
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import patch

import test_development_review_a024 as fixtures
from ariyan_trading import review_catalog as catalog

ROOT=Path(__file__).resolve().parents[1]


class Elements(HTMLParser):
    def __init__(self):super().__init__();self.items=[]
    def handle_starttag(self,tag,attrs):self.items.append((tag,dict(attrs)))


class ReviewCatalogA026Tests(unittest.TestCase):
    def setUp(self):
        fixture=fixtures.DevelopmentReviewA024Tests();fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.fixture=fixture;self.root=fixture.root
        fixture.run_review();self.first=fixture.destination
        for job in fixture.request['jobs']:
            job['job_id']='other-'+job['job_id'];job['config']['cash_currency']='EUR'
        spec=replace(fixture.spec,quote_currency='EUR',settlement_currency='EUR',price_unit='EUR_PER_SHARE')
        fixture.instrument.write_text(json.dumps(spec.to_record()))
        fixture.request['experiment_note']='Second synthetic fixed account; not independent validation.'
        fixture.save();self.second=self.root/'second-review';fixture.run_review(self.second)
        self.destination=self.root/'catalog'

    def build(self,reviews=None,destination=None):
        return catalog.build_catalog([self.first,self.second] if reviews is None else reviews,
                                     destination or self.destination)

    def reject(self,**kwargs):
        with self.assertRaises((ValueError,OSError,TypeError,KeyError)):self.build(**kwargs)
        self.assertFalse(self.destination.exists())

    def test_index_links_and_copied_pages_match_inspected_source_bytes(self):
        before={p:p.read_bytes() for folder in (self.first,self.second) for p in folder.rglob('*') if p.is_file()}
        record=self.build()
        self.assertEqual(record['review_count'],2);self.assertEqual(record['job_count'],4)
        self.assertEqual([r['source_directory_label'] for r in record['reviews']],[str(self.first),str(self.second)])
        for index,folder in enumerate((self.first,self.second)):
            entry=record['reviews'][index]
            self.assertEqual((self.destination/entry['html_file']).read_bytes(),(folder/'REVIEW.html').read_bytes())
            self.assertEqual(entry['summary_table'],json.loads((folder/'COMPLETE.json').read_bytes())['summary_table'])
        for name,digest in record['files_sha256'].items():
            self.assertEqual(hashlib.sha256((self.destination/name).read_bytes()).hexdigest(),digest)
        parser=Elements();parser.feed((self.destination/'index.html').read_text(encoding='utf-8'))
        links=[attrs['href'] for tag,attrs in parser.items if tag=='a']
        self.assertTrue(links)
        self.assertTrue(all(re.fullmatch(r'reviews/review-[0-9]{2}\.html',link) for link in links))
        self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_no_replay_or_original_dataset_reads(self):
        self.fixture.fixture.csv.unlink();self.fixture.fixture.plan_path.unlink()
        with (patch.object(catalog.batch,'run_session_replay',side_effect=AssertionError('No replay')),
              patch.object(catalog.exports,'verify_development_export',side_effect=AssertionError('No originals'))):
            record=self.build()
        for name in ('portfolio_aggregation_performed','replay_rerun','source_authenticity_established','strategy_promoted','live_authorized'):
            self.assertIs(record[name],False)
        self.assertEqual(record['out_of_sample_status'],'NOT_ESTABLISHED')
        self.assertNotIn('portfolio_return_pct',record)

    def test_source_order_and_separate_currency_rows_preserved(self):
        record=self.build(reviews=[self.second,self.first])
        self.assertEqual(record['reviews'][0]['source_directory_label'],str(self.second))
        raw=(self.destination/'index.html').read_text(encoding='utf-8')
        self.assertLess(raw.index('other-synthetic-base'),raw.index('1 · second-review'))
        self.assertIn('USD',raw);self.assertIn('EUR',raw);self.assertIn('no combined portfolio',raw)

    def test_exact_duplicate_batches_rejected_including_copied_folders(self):
        self.reject(reviews=[self.first,self.first])
        duplicate=self.root/'copied';shutil.copytree(self.first,duplicate)
        self.reject(reviews=[self.first,duplicate])

    def test_review_count_types_and_incomplete_reviews_rejected(self):
        for reviews in ([],[self.first]*9,str(self.first)):
            self.reject(reviews=reviews)
        (self.second/'COMPLETE.json').unlink();self.reject()

    def test_all_reviews_inspected_before_output_creation(self):
        (self.second/'REVIEW.html').write_bytes(b'changed')
        self.reject()
        self.assertTrue((self.first/'COMPLETE.json').exists())

    def test_existing_destination_and_source_descendants_never_adopted(self):
        inside=self.first/'catalog'
        with self.assertRaises(ValueError):self.build(destination=inside)
        self.assertFalse(inside.exists())
        self.destination.mkdir();keep=self.destination/'keep.bak';keep.write_text('keep')
        with patch.object(catalog,'_prepare') as prepare,self.assertRaises(ValueError):self.build()
        prepare.assert_not_called();self.assertEqual(keep.read_text(),'keep')

    def test_symlink_sources_and_missing_parent_rejected(self):
        linked=self.root/'linked';linked.symlink_to(self.first,target_is_directory=True)
        self.reject(reviews=[linked])
        with self.assertRaises(ValueError):self.build(destination=self.root/'absent/catalog')
        self.assertFalse((self.root/'absent').exists())

    def test_untrusted_folder_labels_are_escaped_and_no_active_remote_elements(self):
        record=self.build()
        # Exercise the literal attack in the renderer so the filesystem need
        # not accept angle brackets in a directory name.
        record['reviews'][0]['display_label']='<img src=x onerror=alert(1)>'
        raw=catalog._render(record['reviews']).decode('utf-8')
        self.assertIn('&lt;img',raw);self.assertNotIn('<img',raw)
        parser=Elements();parser.feed(raw)
        for tag,attrs in parser.items:
            self.assertNotIn(tag,('script','img','iframe','object','form','link'))
            self.assertFalse(any(name.startswith('on') for name in attrs))
            self.assertNotIn('src',attrs)
        self.assertIn("default-src 'none'",raw)

    def test_inspection_claims_must_have_supported_false_authority_flags(self):
        original=catalog.inspector.inspect_review
        def changed(folder):
            result=original(folder);result['live_authorized']=True;return result
        with patch.object(catalog.inspector,'inspect_review',side_effect=changed):self.reject()

    def test_completion_or_html_changes_during_capture_rejected(self):
        original=catalog.inspector.inspect_review
        for name in ('COMPLETE.json','REVIEW.html'):
            target=self.first/name;before=target.read_bytes()
            def changed(folder):
                result=original(folder)
                target.write_bytes(before+b' ')
                return result
            with patch.object(catalog.inspector,'inspect_review',side_effect=changed):self.reject()
            target.write_bytes(before)

    def test_source_snapshot_change_after_copy_aborts_output(self):
        original=catalog._recheck
        def changed(retained,sources):
            if self.destination.exists():
                target=self.first/'COMPLETE.json';target.write_bytes(target.read_bytes()+b' ')
            return original(retained,sources)
        with patch.object(catalog,'_recheck',side_effect=changed):self.reject()

    def test_implementation_change_and_byte_bounds_prevent_completion(self):
        sources=catalog._sources()
        with patch.object(catalog,'_sources',side_effect=[sources,sources,{**sources,'review_catalog.py':'0'*64}]):self.reject()
        for name in ('MAX_COPIED_HTML_BYTES','MAX_INDEX_BYTES','MAX_METADATA_BYTES'):
            with patch.object(catalog,name,1):self.reject()

    def test_write_failure_cleans_owned_outputs_preserving_sources(self):
        original=Path.open
        class Broken:
            def __init__(self,stream):self.stream=stream
            def __enter__(self):return self
            def __exit__(self,*args):self.stream.close()
            def write(self,raw):self.stream.write(raw[:10]);raise OSError('Synthetic interruption')
        def broken(path,*args,**kwargs):
            stream=original(path,*args,**kwargs)
            return Broken(stream) if path.name=='CATALOG.json' and args and args[0]=='xb' else stream
        before=(self.first/'REVIEW.html').read_bytes()
        with patch.object(Path,'open',new=broken):self.reject()
        self.assertEqual((self.first/'REVIEW.html').read_bytes(),before)

    def test_output_copy_mutation_and_foreign_file_are_not_accepted(self):
        original=catalog._recheck
        def changed(retained,sources):
            result=original(retained,sources)
            if self.destination.exists():
                target=self.destination/'reviews/review-00.html';target.write_bytes(target.read_bytes()+b' ')
            return result
        with patch.object(catalog,'_recheck',side_effect=changed):self.reject()
        def foreign(retained,sources):
            result=original(retained,sources)
            if self.destination.exists():(self.destination/'other').write_text('preserve')
            return result
        with patch.object(catalog,'_recheck',side_effect=foreign),self.assertRaises(ValueError):self.build()
        self.assertEqual((self.destination/'other').read_text(),'preserve')
        self.assertFalse((self.destination/'CATALOG.json').exists())

    def test_directory_race_preserves_other_writer(self):
        original=Path.mkdir
        def racing(path,*args,**kwargs):
            if path==self.destination:
                original(path,*args,**kwargs);(path/'other').write_text('other')
                raise FileExistsError('Synthetic race')
            return original(path,*args,**kwargs)
        with patch.object(Path,'mkdir',new=racing),self.assertRaises(FileExistsError):self.build()
        self.assertEqual((self.destination/'other').read_text(),'other')

    def test_context_independence_catalog_digest_and_portable_copies(self):
        first=self.build()
        second=self.root/'second-catalog'
        with localcontext() as context:
            context.prec=2;context.traps[Inexact]=True
            self.assertEqual(first,self.build(destination=second))
        body={k:v for k,v in first.items() if k!='catalog_sha256'}
        self.assertEqual(first['catalog_sha256'],hashlib.sha256(catalog.VERSION.encode()+b'\0'+catalog.batch.files._canonical(body)).hexdigest())
        relocated=self.root/'relocated';shutil.copytree(self.destination,relocated)
        shutil.rmtree(self.first);shutil.rmtree(self.second)
        for entry in first['reviews']:self.assertTrue((relocated/entry['html_file']).is_file())

    def test_fresh_process_determinism_and_cli_rejection(self):
        outputs=[]
        for name in ('one','two'):
            target=self.root/name
            run=subprocess.run([sys.executable,'-m','ariyan_trading.review_catalog','--review',str(self.first),str(self.second),
                '--destination',str(target)],cwd=self.root,env={**os.environ,'PYTHONPATH':str(ROOT/'app')},capture_output=True,text=True)
            self.assertEqual(run.returncode,0,run.stderr);self.assertIn('NO REPLAY',run.stdout)
            outputs.append((target/'CATALOG.json').read_bytes())
        self.assertEqual(*outputs)
        with patch('sys.stderr',new=io.StringIO()),self.assertRaises(SystemExit) as raised:
            catalog.main(['--review',str(self.first),str(self.first),'--destination',str(self.destination)])
        self.assertEqual(raised.exception.code,2)


if __name__=='__main__':unittest.main()
