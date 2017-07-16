import os
import pep8
import sys

from collections import defaultdict
from io import StringIO

from django.conf import settings
from django.test import TestCase
from pyflakes.scripts.pyflakes import checkPath

import gemcore


PACKAGES = [gemcore]


class Pep8ConformanceTestCase(TestCase):

    exclude = ['migrations']

    def setUp(self):
        super(Pep8ConformanceTestCase, self).setUp()
        self.errors = {}
        self.pep8style = pep8.StyleGuide(
            counters=defaultdict(int),
            doctest='',
            exclude=self.exclude,
            filename=['*.py'],
            ignore=[],
            messages=self.errors,
            repeat=True,
            select=[],
            show_pep8=False,
            show_source=False,
            max_line_length=79,
            quiet=0,
            statistics=False,
            testsuite='',
            verbose=0
        )

    def test_pep8_conformance(self):
        for package in PACKAGES:
            self.pep8style.input_dir(os.path.dirname(package.__file__))
        self.assertEqual(self.pep8style.options.report.total_errors, 0)


class PyflakesAnalysisTestCase(TestCase):

    def test_pyflakes_analysis(self):
        old_stdout = sys.stdout
        sys.stdout = StringIO()
        try:
            for package in PACKAGES:
                self._run_pyflakes_analysis(package)
            errors = sys.stdout.getvalue().splitlines()
        finally:
            # revert stdout so pdb can be used below
            sys.stdout = old_stdout

        ignore_file = getattr(settings, 'PYFLAKES_IGNORE_FILE', None)
        if ignore_file is not None:
            with open(ignore_file) as f:
                ignores = map(str.strip, f.readlines())
            for error in errors[:]:
                if any(i in error for i in ignores):
                    errors.remove(error)

        msg = 'Please fix the following pyflakes errors:\n%s'
        self.assertEqual(errors, [], msg % '\n'.join(errors))

    def _run_pyflakes_analysis(self, package):
        package_path = os.path.dirname(package.__file__)
        for dir_path, dir_names, file_names in os.walk(package_path):
            for file_name in file_names:
                if file_name.endswith('.py'):
                    file_path = os.path.join(dir_path, file_name)
                    checkPath(file_path)
