# -*- coding: utf-8 -*-

import os

from django.test import TestCase

from gemcore.tests.factory import Factory


class BaseTestCase(TestCase):

    factory = Factory()
    maxDiff = None

    def data_file(self, filename):
        return os.path.join(os.path.dirname(__file__), 'data', filename)
