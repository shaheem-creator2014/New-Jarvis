import unittest
from unittest.mock import patch
from agent.calculator import calculate
from agent.conversation import Assistant
from agent.data import selected_source
from agent.vault import KnowledgeIndex


class CalculatorTests(unittest.TestCase):
    def test_exact_arithmetic_and_precedence(self):
        for query, expected in [('199 × 599', '119,201'), ('What is 1+1?', '2'),
                                ('Calculate (12 + 8) / 5', '4'), ('0.1 + 0.2', '0.3'),
                                ('-4 * -3', '12'), ('2^10', '1,024'),
                                ('199 multiplied by 599', '119,201'), ('3 x 7', '21')]:
            with self.subTest(query=query):
                outcome = calculate(query)
                self.assertTrue(outcome['ok'])
                self.assertEqual(outcome['calculation']['result'], expected)
                self.assertTrue(outcome['calculation']['exact'])

    def test_rounding_is_labeled(self):
        outcome = calculate('1/3')
        self.assertFalse(outcome['calculation']['exact'])
        self.assertIn('approximately', outcome['spoken'])

    def test_errors_do_not_fall_back_to_model(self):
        for query in ['1/0', '(1+2', '2**99999999', '9'*161]:
            with self.subTest(query=query):
                self.assertFalse(calculate(query)['ok'])

    def test_non_arithmetic_and_code_are_not_evaluated(self):
        for query in ['CR7 total goals', 'Explain Python', '__import__("os").system("whoami")',
                      'open calculator', '1+1; print(2)']:
            self.assertIsNone(calculate(query))

    def test_assistant_bypasses_ollama_and_records_turn(self):
        assistant = Assistant(KnowledgeIndex(selected_source()).build())
        _, session = assistant.session()
        with patch.object(assistant.ai, 'respond') as model:
            outcome = assistant.process(session, '199 × 599', 'chat')
        model.assert_not_called()
        self.assertEqual(outcome['calculation']['result'], '119,201')
        self.assertEqual(len(session['history']), 2)
