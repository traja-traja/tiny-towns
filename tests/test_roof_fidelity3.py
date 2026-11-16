"""Protocol guards: isolate parameters, restore globals, preserve fallback truth."""
import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import roof_fidelity3 as experiment
import roof_simplify_roofer as native


class FidelityProtocol(unittest.TestCase):
    def test_only_intended_native_parameters_change(self):
        old=native.native_variant_command('roofer_c035','train','footprints','out')
        with experiment.configured_adapter():
            for profile,cfg in experiment.PROFILES.items():
                command=native.native_variant_command(profile,'train','footprints','out')
                allowed={old.index('--complexity-factor')+1,old.index('--plane-detect-epsilon')+1}
                if 'fallback_planes' in cfg:
                    allowed|={old.index('--lod11-fallback-planes')+1,old.index('--lod11-fallback-time')+1}
                self.assertEqual(len(old),len(command))
                self.assertTrue(all(a==b for i,(a,b) in enumerate(zip(old,command)) if i not in allowed))
                self.assertGreater(float(command[old.index('--complexity-factor')+1]),.888)
                self.assertEqual(command[old.index('--plane-detect-epsilon')+1],str(cfg['plane_detect_epsilon_m']))
                self.assertEqual(command[command.index('--lod11-fallback-time')+1],str(cfg.get('fallback_time_ms',10000)))
                self.assertEqual(command[command.index('--lod11-fallback-planes')+1],str(cfg.get('fallback_planes',120)))

    def test_global_configuration_restored_on_exception(self):
        profiles,sources,command=native.PROFILES,native.SOURCE_FILES,native.native_variant_command
        with self.assertRaisesRegex(RuntimeError,'test'):
            with experiment.configured_adapter():
                self.assertIsNot(native.PROFILES,profiles)
                self.assertIn('scripts/roof_fidelity3.py',native.SOURCE_FILES)
                self.assertIn('scripts/roof_simplification_common.py',native.SOURCE_FILES)
                raise RuntimeError('test')
        self.assertIs(native.PROFILES,profiles)
        self.assertIs(native.SOURCE_FILES,sources)
        self.assertIs(native.native_variant_command,command)

    def test_fallback_is_not_mistaken_for_requested_lod(self):
        self.assertEqual(native.native_model_status({'status':'ok','lods':['2.2'],
            'attributes':{'rf_extrusion_mode':'lod11_fallback'}}),'lod11_fallback')
        self.assertEqual(native.native_model_status(None),'missing_output')

    def test_budget_guard_rejects_before_execution(self):
        for repeats,budget in [(3,600),(2,601),(2,0)]:
            with self.assertRaises(ValueError):
                experiment.run(repeats,budget)


if __name__=='__main__':
    unittest.main()
