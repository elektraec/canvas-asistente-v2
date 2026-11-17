import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from sys import path
path.insert(0,str(Path(__file__).parents[1]))
from canvas_core import (parse_assignment_url,clean_assignment,summary_counts,
                         validate_grades,safe_zero_candidates,build_form,verify_submission)

class TestCore(unittest.TestCase):
    def setUp(self):
        self.assignment={'rubric':[{'id':'c1','points':2.0,'ratings':[{'id':'r2','points':2.0},{'id':'r0','points':0}]}],
                         'points_possible':2,'grading_type':'points','due_at':'2020-01-01T00:00:00Z'}
        self.subs=[{'user_id':1,'submitted_at':'2026-01-01T12:00:00Z','workflow_state':'submitted','score':None},
                   {'user_id':2,'submitted_at':None,'workflow_state':'unsubmitted','score':None,'missing':True}]
        self.data={'schema_version':2,'canvas_base':'https://canvas.example.edu','course_id':10,'assignment_id':20,
                   'grades':[{'user_id':1,'student_name':'X','total':2,'comment':'Adecuado',
                              'criteria':[{'criterion_id':'c1','points':2,'rating_id':'r2','comment':'Cumple'}]}]}
    def test_url(self):
        self.assertEqual(parse_assignment_url('https://canvas.example.edu/courses/10/assignments/20'),('https://canvas.example.edu',10,20))
        with self.assertRaises(ValueError):parse_assignment_url('http://canvas.example.edu/courses/10/assignments/20')
    def test_validation(self):
        r,e=validate_grades(self.data,self.assignment,self.subs,'https://canvas.example.edu',10,20)
        self.assertEqual(len(r),1);self.assertEqual(e,[])
    def test_invalid_sum_and_overwrite(self):
        self.data['grades'][0]['total']=1
        _,errors=validate_grades(self.data,self.assignment,self.subs,'https://canvas.example.edu',10,20)
        self.assertTrue(any('suma' in v for v in errors))
        self.subs[0]['score']=1
        _,errors=validate_grades(self.data,self.assignment,self.subs,'https://canvas.example.edu',10,20)
        self.assertTrue(any('sobrescribe' in v for v in errors))
    def test_zero(self):
        zeros,warnings=safe_zero_candidates(self.subs,self.assignment)
        self.assertEqual([v['user_id'] for v in zeros],[2]);self.assertFalse(warnings)
        self.assignment['has_overrides']=True
        self.assertEqual(safe_zero_candidates(self.subs,self.assignment)[0],[])
    def test_form(self):
        form,comment=build_form(self.data['grades'][0],self.assignment['rubric'])
        self.assertEqual(form['rubric_assessment[c1][rating_id]'],'r2')
        self.assertEqual(form['submission[posted_grade]'],'2.0')
    def test_clean(self):
        self.assertNotIn('secure_params',clean_assignment({'secure_params':'secret','name':'A'}))

if __name__=='__main__':unittest.main()
