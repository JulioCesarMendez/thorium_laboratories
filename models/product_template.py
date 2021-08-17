# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

import itertools
import logging

from odoo import api, fields, models, tools, _, SUPERUSER_ID
from odoo.exceptions import ValidationError, RedirectWarning, UserError
from odoo.osv import expression

_logger = logging.getLogger(__name__)


class ProductTemplate(models.Model):
#    _name = "product.template"
    _inherit = "product.template"

# JCM
#    critearea = fields.One2many(
#        comodel_name='thoriumcorp.lab.test.critearea',
#        inverse_name='test_type_id',
#        string='Parámetros del Exámen'
#    )
# F_JCM

