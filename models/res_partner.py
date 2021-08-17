#
#    Copyright (C) 2020-2030 Thorium Corp FP <help@thoriumcorp.website>
#

from odoo import fields, models


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_healthprof = fields.Boolean(
        string='Health Prof',
        help='Check if the partner is a health professional'
    )

# ****************************************************************************************
#    name = fields.Char(index=True)
#
#    display_name = fields.Char(compute='_compute_display_name', store=True, index=True)

    identity_id = fields.Char(
        string='CI',
        help='Personal Identity Card ID',
    )
    alias = fields.Char(
        string='Nickname',
        help='Common, not official, name',
    )
    patient_ids = fields.One2many(
        string='Related patients',
        comodel_name='thoriumcorp.patient',
        # compute='_compute_patient_ids_and_count',
        inverse_name='partner_id',
    )
    count_patients = fields.Integer(compute='_count_patients')
    birthdate_date = fields.Datetime(string='DOB')
    age = fields.Char('Age', help="Person's age")
    date_death = fields.Datetime('Time of death')
    deceased = fields.Boolean()
    gender = fields.Selection(
        [
            ('male', 'Male'),
            ('female', 'Female'),
            ('other', 'Other'),
        ],
        'Gender',
    )
    weight = fields.Float()
    weight_uom = fields.Many2one(
        string="Weight unit",
        comodel_name="uom.uom",
        #default=lambda s: s.env['res.lang'].default_uom_by_category('Weight'),
        domain=lambda self: [(
            'category_id', '=',
            self.env.ref('uom.product_uom_categ_kgm').id)
        ])
    is_patient = fields.Boolean(
        string='Is patient?',
        help='Check if the partner is a patient'
    )
#    is_healthprof = fields.Boolean(
#        string='Profesional de Salud',
#        help='Marque si es profesional de salud'
#    )
    unidentified = fields.Boolean(
        string='Unidentified',
        help='Patient is currently unidentified'
    )
    marital_status = fields.Selection(
        [
            ('s', 'Single'),
            ('m', 'Married'),
            ('w', 'Widow(er)'),
            ('d', 'Divorced'),
            ('x', 'Separated')
        ]
    )
    referenced_by = fields.Selection([('medical_center', 'Medical Center')])
# ****************************************************************************************

