import copy
import unittest
from python_service.visit_timeline import build_timeline, TimelineError


def visit(identifier, day, mmse=27, **values):
    return {'visit':identifier, 'days_from_first_mri':day, 'mmse':mmse, **values}


class TimelineTests(unittest.TestCase):
    def test_two_observations_are_not_457_daily_values(self):
        result=build_timeline([visit(1,0),visit(2,457,30)])
        self.assertEqual([point['value'] for point in result['points']],[27,30])
        self.assertEqual(result['observed_count'],2);self.assertEqual(result['span_days'],457)
        self.assertEqual(result['net_observed_change'],3);self.assertEqual(result['imputed_values'],0)
        self.assertIsNone(result['predictions']);self.assertIsNone(result['uncertainty'])

    def test_missing_value_is_preserved_and_connector_does_not_bridge_gap(self):
        result=build_timeline([visit(1,0),visit(2,90,None),visit(3,180,25)])
        self.assertEqual(result['missing_count'],1);self.assertIsNone(result['rows'][1]['value'])
        self.assertEqual(len(result['points']),2);self.assertEqual(result['connectors'],[])

    def test_unknown_date_disables_connectors_without_guessing_position(self):
        result=build_timeline([visit(1,0),visit(2,None),visit(3,180,25)])
        self.assertEqual(result['invalid_count'],1);self.assertEqual(result['connectors'],[])

    def test_zero_is_an_observation(self):
        result=build_timeline([visit(1,0,0)])
        self.assertEqual(result['observed_count'],1);self.assertEqual(result['missing_count'],0)

    def test_empty_and_single_visit_have_no_net_change(self):
        for visits in ([],[visit(1,0)]):
            result=build_timeline(visits)
            self.assertIsNone(result['net_observed_change']);self.assertEqual(result['connectors'],[])

    def test_invalid_mmse_is_never_rounded_or_clipped(self):
        for value in (27.25,-1,31,True,float('nan'),float('inf'),'27'):
            with self.subTest(value=value):
                result=build_timeline([visit(1,0,value)])
                self.assertEqual(result['points'],[]);self.assertEqual(result['invalid_count'],1)

    def test_mri_and_cdr_keep_their_own_units_and_ranges(self):
        rows=[visit(1,0,nwbv=.696106,cdr=.5),visit(2,457,nwbv=.681062,cdr=1)]
        mri=build_timeline(rows,'nwbv');cdr=build_timeline(rows,'cdr')
        self.assertEqual(mri['maximum'],1);self.assertEqual(mri['points'][0]['value'],.696106)
        self.assertEqual(mri['unit'],'比例');self.assertEqual(cdr['maximum'],3)
        self.assertEqual(cdr['points'][0]['value'],.5)

    def test_fractional_global_cdr_and_invalid_mri_are_not_observations(self):
        self.assertEqual(build_timeline([visit(1,0,cdr=.7)],'cdr')['invalid_count'],1)
        self.assertEqual(build_timeline([visit(1,0,nwbv=1.01)],'nwbv')['invalid_count'],1)

    def test_negative_nonfinite_and_boolean_days_do_not_draw(self):
        for day in (-1,float('nan'),float('inf'),True,'457'):
            result=build_timeline([visit(1,day)])
            self.assertEqual(result['points'],[]);self.assertIsNone(result['rows'][0]['day'])

    def test_unsorted_visits_are_ordered_without_modifying_input(self):
        source=[visit(2,457,30),visit(1,0,27)];before=copy.deepcopy(source)
        result=build_timeline(source)
        self.assertEqual([point['visit'] for point in result['points']],[1,2]);self.assertEqual(source,before)

    def test_duplicate_days_and_identifiers_do_not_produce_ambiguous_lines(self):
        result=build_timeline([visit(1,0),visit(2,0,28),visit(3,457,30)])
        self.assertEqual(result['repeated_days'],[0]);self.assertEqual(result['connectors'],[])
        self.assertIsNone(result['net_observed_change'])
        result=build_timeline([visit(1,0),visit(1,457,30)])
        self.assertTrue(result['duplicate_visit_ids']);self.assertEqual(result['connectors'],[])

    def test_schema_and_capacity_do_not_accept_arbitrary_payloads(self):
        for visits,metric in (({},'mmse'),([{}],'mmse'),([visit(True,0)],'mmse'),([visit(1,0)]*1001,'mmse'),([],'risk')):
            with self.assertRaises(TimelineError):build_timeline(visits,metric)


if __name__=='__main__':unittest.main()
