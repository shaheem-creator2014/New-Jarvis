import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent.data import load_configuration

class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'.env'
    def test_supported_settings_and_environment_precedence(self):
        self.path.write_text('# private local configuration\nJARVIS_MODEL="example:small"\nJARVIS_DEMO=1\nELEVENLABS_VOICE_ID=test_voice\n')
        with patch.dict(os.environ,{'JARVIS_MODEL':'owner-choice'},clear=True):
            load_configuration(self.path)
            self.assertEqual(os.environ['JARVIS_MODEL'],'owner-choice')
            self.assertEqual(os.environ['JARVIS_DEMO'],'1')
            self.assertEqual(os.environ['ELEVENLABS_VOICE_ID'],'test_voice')
    def test_no_shell_evaluation(self):
        self.path.write_text('JARVIS_MODEL=$(touch must-not-exist)\n')
        with patch.dict(os.environ,{},clear=True):
            load_configuration(self.path)
            self.assertEqual(os.environ['JARVIS_MODEL'],'$(touch must-not-exist)')
        self.assertFalse((self.path.parent/'must-not-exist').exists())
    def test_invalid_setting_does_not_partially_apply_or_echo_value(self):
        self.path.write_text('JARVIS_MODEL=test\nPATH=PRIVATE-TEST-VALUE\n')
        with patch.dict(os.environ,{},clear=True):
            with self.assertRaises(ValueError) as error:load_configuration(self.path)
            self.assertNotIn('PRIVATE-TEST-VALUE',str(error.exception))
            self.assertNotIn('JARVIS_MODEL',os.environ)
    def test_missing_file_is_optional(self):
        load_configuration(self.path)
