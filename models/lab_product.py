# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import logging
import re

from odoo import api, fields, models, tools, _
from odoo.exceptions import ValidationError
from odoo.osv import expression


from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

class LabProductProduct(models.Model):
    _name = "lab.product.product"
    _inherit = "product.product"
    _description = 'Thorium Corp Product model'

#    test_type = fields.Char(
#        required=True,
#        index=True
#    )

