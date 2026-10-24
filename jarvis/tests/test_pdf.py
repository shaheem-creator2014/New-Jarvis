import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from agent.data import DataSource
from agent.vault import KnowledgeIndex, extract_pdf

class PDFTests(unittest.TestCase):
    def test_missing_extractor_never_installs(self):
        with patch('agent.vault.importlib.util.find_spec',return_value=None):
            with self.assertRaisesRegex(ValueError,'installation needs approval'):extract_pdf(b'%PDF-1.4\nfixture')

    @unittest.skipUnless(importlib.util.find_spec('pypdf'),'Optional pypdf is not installed')
    def test_actual_pdf_text_and_readonly_source(self):
        from pypdf import PdfWriter
        from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);path=root/'robotics.pdf'
            writer=PdfWriter();page=writer.add_blank_page(width=300,height=300)
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
            stream=DecodedStreamObject();stream.set_data(b'BT /F1 12 Tf 30 200 Td (ESP32 robotics PDF fixture) Tj ET')
            page[NameObject('/Contents')]=writer._add_object(stream)
            with path.open('wb') as output:writer.write(output)
            before=path.read_bytes()
            index=KnowledgeIndex(DataSource(root,True)).build()
            self.assertEqual(len(index.documents),1,index.skipped)
            self.assertEqual(index.search('ESP32')[0]['filename'],'robotics.pdf')
            self.assertIn('PDF page 1',index.documents['robotics.pdf'].text)
            self.assertEqual(path.read_bytes(),before)
