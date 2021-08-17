#
#    Copyright (C) 2020-2030 Thorium Corp FP <help@thoriumcorp.website>
#

from odoo import api, fields, models
# from odoo.modules import get_module_resource
from odoo.exceptions import ValidationError


class ThoriumcorpPatient(models.Model):
    _name = 'thoriumcorp.patient'
    _description = 'Patient'
    _inherit = 'thoriumcorp.abstract_entity'

    identification_code = fields.Char(
        string='Identificación interna',
        help='Identificación del paciente provista por el centro de salud',
    )
    general_info = fields.Text(
        string='Información General',
    )
    is_pregnant = fields.Boolean(
        help='¿Esta embarazada?',
    )
    blood_type = fields.Selection(
        [('A', 'A'), ('B', 'B'), ('AB', 'AB'), ('O', 'O')],
        string='Blood Type',
        sort=False,
        compute='patient_blood_info'
    )
    rh = fields.Selection(
        [('+', '+'), ('-', '-')],
        string='Rh',
        compute='patient_blood_info'
    )
    hb = fields.Selection(
        [
            ('aa', 'AA'),
            ('as', 'AS'),
            ('ss', 'SS'),
            ('sc', 'SC'),
            ('cc', 'CC'),
            ('athal', 'A-THAL'),
            ('bthal', 'B-THAL')
        ],
        string='Hb',
        computed='patient_blood_info'
    )
    critical_summary = fields.Text(
        'Important medical conditions related to this patient',
        help='Automated summary of patient important medical conditions '
        'other critical information')
    critical_info = fields.Text(
        'Free text information not included in the automatic summary',
        help='Write any important information on the patient\'s condition,'
        ' surgeries, allergies, ...')

    patient_of_medical_center_id = fields.Many2one(
        string='Medical center',
        comodel_name='medical.center',
    )

#    medical_center_secondary_ids = fields.Many2many(
#        string='Secondary medical center',
#        comodel_name='medical.center',
#    )

    @api.constrains('is_pregnant', 'gender')
    def _check_is_pregnant(self):
        for record in self:
            if record.is_pregnant and record.gender != 'female':
                raise ValidationError(
                    'Invalid selection - Only a female may be pregnant.'
                )

    @api.model
    def _create_vals(self, vals):
        vals = super(ThoriumcorpPatient, self)._create_vals(vals)
        if not vals.get('identification_code'):
            Seq = self.env['ir.sequence']
            vals['identification_code'] = Seq.sudo().next_by_code(
                self._name,
            )
        # vals.update({
        #     'customer': True,
        # })
        return vals

    def patient_blood_info(self):
        self.blood_type = 'A'
        self.rh = '-'
        self.hb = 'aa'

    # def _get_default_image_path(self, vals):
    #     super(ThoriumcorpPatient, self)._get_default_image_path(vals)
    #     return get_module_resource(
    #         'thoriumcorp', 'static/src/img', 'patient-avatar.png'
    #     )

    def toggle_is_pregnant(self):
        self.toggle('is_pregnant')

    def toggle_safety_cap_yn(self):
        self.toggle('safety_cap_yn')

    def toggle_counseling_yn(self):
        self.toggle('counseling_yn')

