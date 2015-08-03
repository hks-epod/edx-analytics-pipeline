import json
import logging
import hashlib
from luigi.s3 import S3Client
import os
import sys
if sys.version_info[:2] <= (2, 6):
    import unittest2 as unittest
else:
    import unittest

from edx.analytics.tasks.url import url_path_join
from edx.analytics.tasks.tests.acceptance.services import fs, db, task, hive, vertica


log = logging.getLogger(__name__)


class AcceptanceTestCase(unittest.TestCase):

    acceptance = 1
    NUM_MAPPERS = 4
    NUM_REDUCERS = 2

    def setUp(self):
        self.s3_client = S3Client()

        config_json = os.getenv('ACCEPTANCE_TEST_CONFIG')
        try:
            with open(config_json, 'r') as config_json_file:
                self.config = json.load(config_json_file)
        except (IOError, TypeError):
            try:
                self.config = json.loads(config_json)
            except TypeError:
                self.config = {}

        # The name of an existing job flow to run the test on
        assert('job_flow_name' in self.config)
        # The git URL of the pipeline repository to check this code out from.
        assert('tasks_repo' in self.config)
        # The branch of the pipeline repository to test. Note this can differ from the branch that is currently
        # checked out and running this code.
        assert('tasks_branch' in self.config)
        # Where to store logs generated by the pipeline
        assert('tasks_log_path' in self.config)
        # The user to connect to the job flow over SSH with.
        assert('connection_user' in self.config)
        # Where the pipeline should output data, should be a URL pointing to a directory.
        assert('tasks_output_url' in self.config)
        # Allow for parallel execution of the test by specifying a different identifier. Using an identical identifier
        # allows for old virtualenvs to be reused etc, which is why a random one is not simply generated with each run.
        assert('identifier' in self.config)
        # A URL to a JSON file that contains most of the connection information for the MySQL database.
        assert('credentials_file_url' in self.config)
        # A URL to a JSON file that contains most of the connection information for the Veritca database.
        assert('vertica_creds_url' in self.config)
        # A URL to a build of the oddjob third party library
        assert 'oddjob_jar' in self.config
        # A URL to a maxmind compatible geolocation database file
        assert 'geolocation_data' in self.config

        self.data_dir = os.path.join(os.path.dirname(__file__), 'fixtures')

        url = self.config['tasks_output_url']
        m = hashlib.md5()
        m.update(self.config['identifier'])
        self.identifier = m.hexdigest()
        self.test_root = url_path_join(url, self.identifier, self.__class__.__name__)

        self.test_src = url_path_join(self.test_root, 'src')
        self.test_out = url_path_join(self.test_root, 'out')

        self.catalog_path = 'http://acceptance.test/api/courses/v2'
        database_name = 'test_' + self.identifier
        schema = 'test_' + self.identifier
        import_database_name = 'import_' + database_name
        export_database_name = 'export_' + database_name
        self.warehouse_path = url_path_join(self.test_root, 'warehouse')
        task_config_override = {
            'hive': {
                'database': database_name,
                'warehouse_path': self.warehouse_path
            },
            'map-reduce': {
                'marker': url_path_join(self.test_root, 'marker')
            },
            'manifest': {
                'path': url_path_join(self.test_root, 'manifest'),
                'lib_jar': self.config['oddjob_jar']
            },
            'database-import': {
                'credentials': self.config['credentials_file_url'],
                'destination': self.warehouse_path,
                'database': import_database_name
            },
            'database-export': {
                'credentials': self.config['credentials_file_url'],
                'database': export_database_name
            },
            'vertica-export': {
                'credentials': self.config['vertica_creds_url'],
                'schema': schema
            },
            'course-catalog': {
                'catalog_url': self.catalog_path
            },
            'geolocation': {
                'geolocation_data': self.config['geolocation_data']
            },
            'event-logs': {
                'source': self.test_src,
                'pattern': tuple(list(self.pattern).extend(self.config['pattern']))
            }
        }

        log.info('Running test: %s', self.id())
        log.info('Using executor: %s', self.config['identifier'])
        log.info('Generated Test Identifier: %s', self.identifier)

        self.import_db = db.DatabaseService(self.config, import_database_name)
        self.export_db = db.DatabaseService(self.config, export_database_name)
        self.task = task.TaskService(self.config, task_config_override, self.identifier)
        self.vertica = vertica.VerticaService(self.config, schema)
        self.hive = hive.HiveService(self.task, self.config, database_name)

        self.reset_external_state()

    def reset_external_state(self):
        self.s3_client.remove(self.test_root, recursive=True)
        self.import_db.reset()
        self.export_db.reset()
        self.hive.reset()
        self.vertica.reset()

    def upload_tracking_log(self, input_file_name, file_date):
        # Define a tracking log path on S3 that will be matched by the standard event-log pattern."
        input_file_path = url_path_join(
            self.test_src,
            'FakeServerGroup',
            'tracking.log-{0}.gz'.format(file_date.strftime('%Y%m%d'))
        )
        with fs.gzipped_file(os.path.join(self.data_dir, 'input', input_file_name)) as compressed_file_name:
            self.s3_client.put(compressed_file_name, input_file_path)

    def execute_sql_fixture_file(self, sql_file_name):
        self.import_db.execute_sql_file(os.path.join(self.data_dir, 'input', sql_file_name))
