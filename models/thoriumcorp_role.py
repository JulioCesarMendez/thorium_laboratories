# Copyright 2017 LasLabs Inc.
# Copyright 2017 Creu Blanca.
# Copyright 2017 Eficent Business and IT Consulting Services, S.L.
# Copyright 2020 LabViv.
# License GPL-3.0 or later (http://www.gnu.org/licenses/gpl.html).

from odoo import models, fields


class ThoriumcorpRole(models.Model):
    _name = 'thoriumcorp.role'
    _description = 'Practitioner Roles'

    name = fields.Char(required=True,)
    description = fields.Char(required=True,)
    active = fields.Boolean(default=True,)
