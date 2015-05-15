__author__ = 'johnbaker'

import re
import sys
import glob
import errno
import unittest
import pandas as pd
import datetime
import edx.analytics.tasks.util.opaque_key_util as opaque_key_util

if sys.version_info[0] < 3:
    from StringIO import StringIO
else:
    from io import StringIO


class DailyStudentEngagementAcceptanceTest(unittest.TestCase):

    # Example file formats:
    # student_engagement_daily_2015-04-13.csv
    # student_engagement_weekly_2015-04-19.csv
    # student_engagement_all_2015-04-06-2015-04-20.csv

    INPUT_FILE = 'student_engagement_acceptance_tracking.log'
    NUM_REDUCERS = 1

    COURSE_1 = "edX/DemoX/Demo_Course"
    COURSE_2 = "edX/DemoX/Demo_Course_2"
    COURSE_3 = "course-v1:edX+DemoX+Demo_Course_2015"

    ALL_COURSES = [COURSE_1, COURSE_2, COURSE_3]

    # We only expect some of the generated files to have any counts at all, so enumerate them.
    NONZERO_OUTPUT = [
        (COURSE_1, '2015-04-13', 'daily'),
        (COURSE_1, '2015-04-16', 'daily'),
        (COURSE_2, '2015-04-13', 'daily'),
        (COURSE_2, '2015-04-16', 'daily'),
        (COURSE_3, '2015-04-09', 'daily'),
        (COURSE_3, '2015-04-12', 'daily'),
        (COURSE_3, '2015-04-13', 'daily'),
        (COURSE_3, '2015-04-16', 'daily'),
        (COURSE_1, '2015-04-19', 'weekly'),
        (COURSE_2, '2015-04-19', 'weekly'),
        (COURSE_3, '2015-04-12', 'weekly'),
        (COURSE_3, '2015-04-19', 'weekly'),
        (COURSE_1, '2015-04-19', 'all'),
        (COURSE_2, '2015-04-19', 'all'),
        (COURSE_3, '2015-04-19', 'all'),
    ]


    def test_student_engagement(self):
        path = '/tmp/student_engagement/'
        outputs = glob.glob(path)


        #
        # Produce student_engagement file list
        # Eg:
        # s3://.../StudentEngagementAcceptanceTest/out/.../student_engagement_daily_2015-04-05.csv
        #
        for interval_type in ['daily', 'weekly', 'all']:

            date_column_name = "date" if interval_type == 'daily' else "end_date"

            for course_id in self.ALL_COURSES:
                hashed_course_id = hashlib.sha1(course_id).hexdigest()
                course_dir = url_path_join(self.test_out, interval_type, hashed_course_id)
                outputs = self.s3_client.list(course_dir)
                outputs = [url_path_join(course_dir, p) for p in outputs if p.endswith(".csv")]

                # There are 14 student_engagement files in the test data directory, and 3 courses.
                if interval_type == 'daily':
                    self.assertEqual(len(outputs), 14)
                elif interval_type == 'weekly':
                    self.assertEqual(len(outputs), 2)
                elif interval_type == 'all':
                    self.assertEqual(len(outputs), 1)

                # Check that the results have data
                for output in outputs:

                    # parse expected date from output.
                    if interval_type == 'all':
                        expected_date = '2015-04-19'
                    else:
                        csv_pattern = '.*student_engagement_.*_(\\d\\d\\d\\d-\\d\\d-\\d\\d)\\.csv'
                        match = re.match(csv_pattern, output)
                        expected_date = match.group(1)

                    dataframe = []
                    with open(output) as csvfile:
                    #with S3Target(output).open() as csvfile:
                        # Construct dataframe from file to create more intuitive column handling
                        dataframe = pd.read_csv(csvfile)
                        dataframe.fillna('', inplace=True)

                    # General validation:
                    self.validate_number_of_columns(len(dataframe.columns))

                    for date in dataframe[date_column_name]:
                        self.validate_date_cell_format(date)

                    for user_name in dataframe["username"]:
                        self.validate_username_string_format(user_name)

                    for email in dataframe["email"]:
                        self.validate_email_string_format(email)

                    for cohort in dataframe["cohort"]:
                        self.validate_cohort_format(cohort)

                    for column_name in dataframe.ix[:, 5:14]:
                        for column_value in dataframe[column_name]:
                            self.validate_problems_videos_forums_textbook_values(column_value)

                    self.validate_within_rows(dataframe)

                    # Validate specific values:
                    for date in dataframe[date_column_name]:
                        self.assertEquals(date, expected_date)

                    for row_course_id in dataframe["course_id"]:
                        self.assertEquals(row_course_id, course_id)

                    if (course_id, expected_date, interval_type) in self.NONZERO_OUTPUT:
                        # TODO: read expected values from fixture and compare:
                        pass
                    else:
                        self.assert_zero_engagement(dataframe)
                        # TODO: check username, email, and cohort names (if any).

    def assert_zero_engagement(self, dataframe):
        """Asserts that all counts are zero."""
        for column_name in dataframe.columns[5:14]:
            for column_value in dataframe[column_name]:
                self.assertEquals(column_value, 0)
        for column_value in dataframe['last_subsection_viewed']:
            self.assertEquals(len(column_value), 0)



    def validate_number_of_columns(self, num_columns):
        """Ensure each student engagement file has the correct number of columns (15)"""
        self.assertTrue(num_columns == 15, msg="Number of columns not equal to 15")

    def validate_date_cell_format(self, date):
        """Ensure date on each row is of the format yyyy-mm-dd"""
        self.assertRegexpMatches(date, '^\d\d\d\d-\d\d-\d\d$')

    def validate_course_id_string_format(self, course_id):
        """Ensure course_id on each row matches a course_id string"""
        self.assertTrue(opaque_key_util.is_valid_course_id(course_id))

    def validate_username_string_format(self, user_name):
        """Ensure user_name on each row matches a user_name string"""
        self.assertRegexpMatches(user_name, '^.{1,}$')

    def validate_email_string_format(self, email):
        """Ensure email address on each row matches an email address"""
        self.assertRegexpMatches(email, '^([^@|\s]+@[^@]+\.[^@|\s]+)$')

    def validate_cohort_format(self, cohort):
        """Cohort is present or not"""
        if cohort:
            self.assertRegexpMatches(str(cohort), '^.+$')

    def validate_problems_videos_forums_textbook_values(self, value):
        """Ensure problems,videos,forum and texbook column values are greater than or equal to 0"""
        self.assertTrue(int(value) >= 0, msg="Problems,Videos,Forums or Textbook fields are not greater or equal to 0.")

    def validate_within_rows(self, dataframe):
        # Validate various comparisons within a given row. Eg:
        # 1. problems correct gte to problems_attempted
        for index, row in dataframe.iterrows():
            # Number of correct problems should be equal to or lower than problems_attempted
            self.assertTrue(row["problems_correct"] <= row["problems_attempted"],
                            msg="Greater number of problems_correct than problems_attempted.")



if __name__ == '__main__':
    unittest.main()