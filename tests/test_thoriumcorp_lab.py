##############################################################################
#
#    Copyright (C) 2020-2030 Thorium Corp FP <help@thoriumcorp.website>
#
##############################################################################

from odoo import ModuleTestCase


class ThoriumcorpLabTestCase(ModuleTestCase):
    '''
    Test Thorium Corp FP Lab module.
    '''
    module = 'thoriumcorp_lab'


def suite():
    suite = thorium.tests.test_thorium.suite()
    suite.addTests(unittest.TestLoader().loadTestsFromTestCase(
        ThoriumcorpLabTestCase))
    return suite
