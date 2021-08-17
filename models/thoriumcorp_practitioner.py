#
#    Copyright (C) 2020-2030 Thorium Corp FP <help@thoriumcorp.website>
#

from odoo import api, fields, models, modules


class ThoriumcorpPractitioner(models.Model):
    _name = 'thoriumcorp.practitioner'
    _description = 'Thoriumcorp Practitioner'
    _inherit = 'thoriumcorp.abstract_entity'
    _sql_constraints = [(
        'thoriumcorp_practitioner_unique_code',
        'UNIQUE (code)',
        'Internal ID must be unique',
    )]

    thoriumcorp_center_primary_id = fields.Many2one(
        string='Primary thoriumcorp center',
        comodel_name='medical.center',
    )
#    thoriumcorp_center_secondary_ids = fields.Many2many(
#        string='Secondary thoriumcorp center',
#        comodel_name='medical.center',
#    )
    code = fields.Char(
        string='Internal ID',
        help='Unique ID for this professional',
        required=True,
        default=lambda s: s.env['ir.sequence'].next_by_code(s._name + '.code'),
    )
    role_ids = fields.Many2many(
        string='Roles',
        comodel_name='thoriumcorp.role',
    )
    practitioner_type = fields.Selection(
        [
            ('internal', 'Internal Entity'),
            ('external', 'External Entity')
        ],
        string='Entity Type',
    )
    specialty_id = fields.Many2one(
        string="Main specialty",
        comodel_name='thoriumcorp.specialty',
    )
    specialty_ids = fields.Many2many(
        string='Other specialties',
        comodel_name='thoriumcorp.specialty'
    )
    info = fields.Text(string='Extra info')

    @api.model
    def _get_default_image_path(self, vals):
        res = super(ThoriumcorpPractitioner, self)._get_default_image_path(vals)
        if res:
            return res

        practitioner_gender = vals.get('gender', 'male')
        if practitioner_gender == 'other':
            practitioner_gender = 'male'

        image_path = modules.get_module_resource(
            'thoriumcorp_practitioner',
            'static/src/img',
            'practitioner-%s-avatar.png' % practitioner_gender,
        )
        return image_path


#class ThoriumcorpPatientDisease(models.Model):
#    _name = 'thoriumcorp.patient_disease'
#    _inherit = 'thoriumcorp.patient_disease'
#
#    practitioner_id = fields.Many2one(
#        comodel_name='thoriumcorp.practitioner',
#        string='Physician', index=True
#    )
