import unittest
from benchmark import evaluate_agent_response


class BenchmarkContractTests(unittest.TestCase):
    def evaluate(self, reply):
        return evaluate_agent_response({}, 0, reply, 0.1, 'direct')

    def test_clarification_is_valid_but_not_completed_trip(self):
        result = self.evaluate({'reply': 'Куда хотите поехать?', 'updatedOptions': {}})
        self.assertTrue(result['passed'])
        self.assertFalse(result['trip_completed'])
        self.assertIsNone(result['logistics_ok'])
        self.assertIsNone(result['tradeoffs_ok'])

    def option(self):
        return {'available': True, 'hotel': {'pricePerNight': 2000, 'nights': 2},
                'transport': {'price': 5000}, 'extras': [{'price': 1000}],
                'fairPriceBreakdown': {'grand_total_rub': 10000, 'refundable_deposit_rub': 1000}}

    def test_single_real_option_is_valid(self):
        result = self.evaluate({'reply': 'Доступен один отель', 'updatedOptions': {'A': self.option()}})
        self.assertTrue(result['passed'])
        self.assertTrue(result['trip_completed'])

    def test_expensive_trip_rejection_does_not_violate_budget(self):
        result = self.evaluate({'reply': 'Нет вариантов в пределах бюджета', 'updatedOptions': {},
                                'budget_rub': 10000, 'budget_respected': False, 'trip_assembled': False})
        self.assertTrue(result['passed'])
        self.assertFalse(result['trip_completed'])

    def test_deposit_cannot_be_hidden_by_claiming_budget_respected(self):
        result = self.evaluate({'reply': 'Готово', 'updatedOptions': {'A': self.option()},
                                'budget_rub': 10000, 'budget_respected': True})
        self.assertFalse(result['passed'])
        self.assertFalse(result['budget_ok'])

    def test_inconsistent_total_fails(self):
        option = self.option()
        option['fairPriceBreakdown']['grand_total_rub'] = 9000
        result = self.evaluate({'reply': 'Готово', 'updatedOptions': {'A': option}})
        self.assertFalse(result['passed'])

    def test_missing_contract_or_empty_text_fails(self):
        for reply in ({'reply': 'Готово'}, {'reply': '', 'updatedOptions': {}},
                      {'reply': 'Готово', 'updatedOptions': {'A': {}}}):
            self.assertFalse(self.evaluate(reply)['passed'])


if __name__ == '__main__':
    unittest.main()
