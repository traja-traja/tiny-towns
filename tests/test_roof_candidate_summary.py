"""Summary counts only current parent captures, preserving missing legacy data."""
import json,sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from roof_candidate_summary import summarize_candidate_telemetry,render_candidate_telemetry
from roof_v2_report import render_report


def trace(family,considered,fit,geometry=0.,attempts=None):
    return dict(schema='candidate-trace-test',detailed=True,
        families=[dict(family=family,considered=considered,skipped=0,failed=0,selected=1,
                       fitting_seconds=fit,geometry_seconds=geometry,overhead_seconds=.1)],attempts=attempts or [])


def part(log,seconds=5.,analytic=1.,side='current',index=0):
    result={'timing':{'total_seconds':seconds,'observed_ridges_seconds':analytic},'diagnostics':{},'model':{'metadata':{}}}
    if log is not None:result['diagnostics']['candidate_telemetry']=log
    return dict(part_index=index,display_variant=side,result=result)


class CandidateSummaryTests(unittest.TestCase):
    def test_current_parent_capture_is_not_doubled_by_previous_or_children(self):
        current=part(trace('straight_skeleton',4,2.,.5,attempts=[
            dict(family='straight_skeleton',stage='eligibility',status='eligible',reason='complex'),
            dict(family='straight_skeleton',stage='eligibility',status='skipped',reason='small')]))
        current['result']['model']['metadata']['bodies']=[{'result':part(trace('straight_skeleton',99,99.))['result']}]
        other=part(trace('gabled',2,.3),seconds=2,analytic=.25,index=1)
        document={'comparison_mode':'batch','buildings':[{'id':'a','address':'A','parts':[
            part(trace('straight_skeleton',100,100),side='previous'),current,other]}]}
        summary=summarize_candidate_telemetry(document)
        family=next(x for x in summary['families'] if x['family']=='straight_skeleton')
        self.assertEqual(family['considered'],4)
        self.assertEqual(family['buildings_considered'],1)
        self.assertAlmostEqual(family['total_seconds'],2.6)
        self.assertEqual(summary['recorded_parts'],2)
        self.assertEqual(summary['buildings'][0]['roof_compute_seconds'],7.)
        self.assertEqual(summary['buildings'][0]['analytical_seconds'],1.25)
        self.assertEqual(summary['skeleton']['eligible_calls'],1)
        self.assertEqual(summary['skeleton']['skipped_calls'],1)
        self.assertEqual(summary['skeleton']['eligible_buildings'],1)
        self.assertEqual(summary['skeleton']['skipped_buildings'],1)

    def test_missing_legacy_and_failed_partial_measurements_are_explicit(self):
        failed={'part_index':0,'status':'failed','candidate_telemetry':trace('gabled',3,.7),
                'timing':{'total_seconds':1.2},'error':{'message':'failed'}}
        doc={'buildings':[{'id':'legacy','parts':[part(None,seconds=8.)]},
            {'id':'error','parts':[failed]}]}
        summary=summarize_candidate_telemetry(doc)
        self.assertEqual(summary['missing_parts'],1)
        legacy=next(x for x in summary['buildings'] if x['id']=='legacy')
        self.assertIsNone(legacy['skeleton_considered'])
        self.assertFalse(legacy['telemetry_complete'])
        bad=next(x for x in summary['buildings'] if x['id']=='error')
        self.assertEqual(bad['roof_compute_seconds'],1.2)
        self.assertIsNone(bad['analytical_seconds'])
        self.assertEqual(bad['families'][0]['considered'],3)
        self.assertIn('Neúplná telemetrie',render_candidate_telemetry(summary))
        self.assertIn('Chybějící měření',render_candidate_telemetry(summarize_candidate_telemetry({'buildings':[doc['buildings'][0]]})))

    def test_old_comparison_uses_latest_part_and_escaping_is_safe(self):
        log=trace('straight_skeleton',1,.1,attempts=[dict(family='straight_skeleton',stage='eligibility',status='skipped',reason='<img src=x onerror=bad>')])
        older=part(trace('flat',90,90),side=None)
        latest=part(log,side=None)
        data={'comparison_mode':'legacy','buildings':[{'id':'a\" onclick=bad','address':'<script>bad</script>','parts':[older,latest]}]}
        summary=summarize_candidate_telemetry(data)
        self.assertEqual(len(summary['families']),1)
        rendered=render_candidate_telemetry(summary)
        self.assertNotIn('<script>',rendered)
        self.assertNotIn('<img ',rendered)
        self.assertIn('&lt;script&gt;',rendered)
        self.assertIn('&lt;img ',rendered)
        self.assertIn('a%22%20onclick%3Dbad',rendered)

    def test_report_places_summary_after_models_without_recomputing(self):
        data={'schema':'roof-v2/1','city':'ceske-budejovice','buildings':[{'id':'safe','parts':[part(trace('flat',1,.02))]}]}
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);source=base/'results.json';source.write_text(json.dumps(data),encoding='utf8')
            three=base/'three.js';three.write_text('export const VERSION="test";',encoding='utf8')
            output=base/'report.html';render_report(source,output,three)
            rendered=output.read_text(encoding='utf8')
        self.assertGreater(rendered.index('id="candidate-performance"'),rendered.index('</main>'))
        self.assertNotIn('@@CANDIDATE_SUMMARY@@',rendered)
        self.assertIn('Domy podle délky výpočtu',rendered)

if __name__=='__main__':unittest.main()
