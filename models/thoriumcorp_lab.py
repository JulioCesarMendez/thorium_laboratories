#
#    Copyright (C) 2020-2030 Thorium Corp FP <help@thoriumcorp.website>
#

import datetime
from odoo import models, fields, api, _
from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta, date


class ThoriumcorpPatient(models.Model):
    _inherit = 'thoriumcorp.patient'
    _description = 'Patient lab tests'

    lab_test_ids = fields.One2many(
        comodel_name='thoriumcorp.lab.test.requests',
        inverse_name='patient_id',
        string='Lab Tests Required'
    )

#class ThoriumcorpPatientDisease(models.Model):
#    _inherit = 'thoriumcorp.patient_disease'
#    _description = 'Patient Conditions History'
#
##    lab_confirmed = fields.Boolean(
#        string='Lab Confirmed',
#        help='Confirmed by laboratory test'
#    )
#
#    lab_test = fields.Many2one(
#        comodel_name='thoriumcorp.lab.test.result',
#        string='Lab Test',
#        # domain=[
#        #     ('patient_id', '=', 'name')
#        # ],
#        depends=['name'],
#        # states={'invisible': Not(Bool(Eval('lab_confirmed')))},
#        help='Lab test that confirmed the condition'
#    )

class ThoriumcorpPatientLabTest(models.Model):
    _name = 'thoriumcorp.lab.test.requests'
    _description = 'Patient Lab Test'

    name = fields.Char(
        string='Order',
        readonly=False,
        required=True,
        copy=False,
        default='New'
    )
#    category = fields.Many2one(
#        comodel_name='thoriumcorp.lab.categories',
#        string='Category',
#        help='Category of this lab test'
#    )
    test_type = fields.Many2one(
        comodel_name='thoriumcorp.lab.test.type',
        string='Test Type',
        required=True,
#        domain= "[('category', '=', category)]",
        index=True
    )
    date = fields.Datetime(
        string='Date',
        index=True
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('tested', 'Tested'),
            ('ordered', 'Ordered'),
            ('cancel', 'Cancel'),
        ],
        string='State',
        readonly=False,
        index=True
    )
    patient_id = fields.Many2one(
        comodel_name='thoriumcorp.patient',
        string='Patient',
        required=True,
        index=True
    )
#    doctor_id = fields.Many2one(
#        string='Doctor',
#        comodel_name='thoriumcorp.practitioner',
#        help='Doctor who Request the lab test',
#        readonly=False,
#    )

    referenced_by = fields.Many2one(
        string='Medical center',
        comodel_name='medical.center',
    )

    urgent = fields.Boolean(
        string='Urgent'
    )
    test_result = fields.One2many(
        comodel_name='thoriumcorp.lab.test.result',
        inverse_name='test_request',
        string='Result'
    )
    result_count = fields.Char(
        string='Result'
    )

    def get_result(self):
        self.ensure_one()
        result_id = self.test_result.id
#        view_id = self.env.ref('thoriumcorp.lab.thoriumcorp_lab_test_result_form').id
        view_id = self.env.ref('thoriumcorp_lab_test_result_form').id
        return {
            'name': _('Lab Test Result'),
            'type': 'ir.actions.act_window',
            'view_type': 'form',
            'view_mode': 'form',
            'res_model': 'thoriumcorp.lab.test.result',
            'res_id': result_id,
            'view_id': view_id,
            'views': [(view_id, 'form')],
            'context': {
                'default_test_request': self.id,
                'default_patient': self.patient_id.id,
                'default_date_requested': self.date,
                'default_test': self.test_type.id
            }
        }


    @api.model
    def default_get(self, fields):
        res = super(ThoriumcorpPatientLabTest, self).default_get(fields)
        res.update(
            {
                'date': datetime.now(),
                'state': 'draft'
            }
        )
        return res

    @api.model
    def create(self, vals):
#        if vals.get('name', 'New') == 'New':
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code(self._name) or 'New'
        return super(ThoriumcorpPatientLabTest, self).create(vals)

class ThoriumcorpLabTestResult(models.Model):
    _name = 'thoriumcorp.lab.test.result'
    _description = 'Lab Test Results'

    name = fields.Char(
        string='ID',
        help="Lab result ID",
        readonly=True,
        required=True,
        copy=False,
        default='New'
    )
    test = fields.Many2one(
        comodel_name='thoriumcorp.lab.test.type',
        string='Test type',
        help="Lab test type",
        readonly=True,
        required=True,
        index=True
    )
    patient = fields.Many2one(
        comodel_name='thoriumcorp.patient',
        string='Patient',
        help="Patient ID",
        required=True,
        readonly=True,
        index=True
    )
    pathologist = fields.Many2one(
        comodel_name='thoriumcorp.practitioner',
        string='Pathologist',
        help="Pathologist",
        index=True
    )
    requestor = fields.Many2one(
        comodel_name='thoriumcorp.practitioner',
        string='Physician',
        help="Doctor who requested the test",
        index=True
    )
    results = fields.Text(
        string='Results'
    )
    diagnosis = fields.Text(
        string='Diagnosis'
    )
    value = fields.One2many(
        comodel_name='thoriumcorp.lab.test.value',
        inverse_name='test_result',
        string='Value Critearea'
    )
    criteria = fields.One2many(
        comodel_name='thoriumcorp.lab.test.critearea',
        inverse_name='thoriumcorp_lab_id',
        string='Lab Test Criteria'
    )
    date_requested = fields.Datetime(
        string='Date requested',
        required=True,
        readonly=True,
        index=True
    )
    date_analysis = fields.Datetime(
        string='Date of the Analysis',
        index=True
    )
    test_request = fields.Many2one(
        comodel_name='thoriumcorp.lab.test.requests',
        readonly=True,
        string='Request'
    )
#    pathology = fields.Many2one(
#        comodel_name='thoriumcorp.pathology',
#        string='Pathology',
#        help='Pathology confirmed / associated to this lab test.'
#    )
    analytes_summary = fields.Text(
        string='Summary'
        # ,
        # compute='get_analytes_summary'
    )

    @api.model
    def default_get(self, fields):
        res = super(ThoriumcorpLabTestResult, self).default_get(fields)
        res.update(
            {
                'date_analysis': datetime.now()
            }
        )
        return res

    # def get_analytes_summary(self):
    #     summ = ""
    #     for analyte in self.critearea:
    #         if analyte.result or analyte.result_text:
    #             res = ""
    #             res_text = ""
    #             if analyte.result_text:
    #                 res_text = analyte.result_text
    #             if analyte.result:
    #                 res = str(analyte.result) + " "
    #             summ = summ + analyte.name + " " + \
    #                 res + res_text + "\n"
    #     self.analytes_summary = summ

    _sql_constraints = [
        (
            'id_uniq',
            'unique(name)',
            'The test ID code must be unique'
        )
    ]

    @api.model
    def create(self, vals):
#        if vals.get('name', 'New') == 'New':
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code(self._name) or 'New'
        return super(ThoriumcorpLabTestResult, self).create(vals)

    @api.onchange('test')
    def onchange_test(self):
        if self.test and self.test.critearea:
            value_ids = self.test.critearea.filtered(
                lambda r: not r.test
            )
            value_id = value_ids[0] if value_ids else False
            self.value = [
                (0, 0, {
                    'name': line.name,
                    'lower_limit': line.lower_limit,
                    'upper_limit': line.upper_limit,
                    'units': line.units
                }) for line in value_ids
            ]

    def button_progress(self):
        for record in self:
            record.write({
                        'state': 'in_progress'
                        })

    def button_close(self):
        for record in self:
            record.write({
                        'state': 'close'
                        })

    def button_cancelled(self):
        for record in self:
            record.write({
                        'state': 'cancel'
                        })

    def button_draft(self):
        for record in self:
            record.write({
                        'state': 'draft'
                        })


class ThoriumcorpLabTestValue(models.Model):
    _name = 'thoriumcorp.lab.test.value'
    _description = 'Lab Test Result Value'

    result = fields.Float(
        string='Value'
    )
    result_text = fields.Char(
        string='Result - Text',
        help='Non-numeric results. For'
        'example qualitative values, morphological, colors ...'
    )
    warning = fields.Boolean(
        string='Warn',
        help='Warns the patient about this'
        ' analyte result'
        ' It is useful to contextualize the result to each patient status'
        ' like age, sex, comorbidities, ...'
    )
    test_result = fields.Many2one(
        comodel_name='thoriumcorp.lab.test.result',
        string='Test Result'
    )
    name = fields.Char(
        string='Analyte',
        required=True,
        index=True,
        translate=True
    )
    lower_limit = fields.Float(
        string='Lower Limit'
    )
    upper_limit = fields.Float(
        string='Upper Limit'
    )
    units = fields.Many2one(
        comodel_name='thoriumcorp.lab.test.units',
        readonly=True,
        string='Units'
    )
    lab_warning_icon = fields.Char(
        string='Lab Warning Icon',
        compute='get_lab_warning_icon',
        default='medical.normal'
    )

    @api.model
    def get_lab_warning_icon(self):
        if (self.warning):
            self.lab_warning_icon = 'thoriumcorp.warning'

    @api.depends('result')
    def on_change_with_warning(self):
        if (self.result and self.lower_limit):
            if (self.result < self.lower_limit):
                self.warning = True

        if (self.result and self.upper_limit):
            if (self.result > self.upper_limit):
                self.warning = True


#class ThoriumcorpLabCategories(models.Model):
#    _name = 'thoriumcorp.lab.categories'
#    _description = 'Lab Test Categories'
#
#    name = fields.Char(
#        string='Category',
#        index=True
#    )
#    detail = fields.Char(
#        string='Detail',
#        index=True
#    )
#    conditions = fields.Char(
#        string='Conditions',
#        index=True
#    )
#
#    sql_constraints = [
#        (
#            'name_uniq',
#            'unique(name)',
#            'The Category name must be unique'
#        )
#    ]


class ThoriumcorpLabTestUnits(models.Model):
    _name = 'thoriumcorp.lab.test.units'
    _description = 'Lab Test Units'

    name = fields.Char(
        string='Unit',
        index=True
    )
    code = fields.Char(
        string='Code',
        index=True
    )

    _sql_constraints = [
        (
            'name_uniq',
            'unique(name)',
            'The Unit name must be unique'
        )
    ]


class ThoriumcorpLabTestType(models.Model):
    _name = 'thoriumcorp.lab.test.type'
    _description = 'Type of Lab test'

    name = fields.Char(
        string='Test',
        help="Test type, eg X-Ray, hemogram,biopsy...",
        required=True,
        index=True,
        translate=True
    )
    code = fields.Char(
        string='Code',
        help="Short name - code for the test",
        required=True,
        index=True
    )
#    category = fields.Many2one(
#        comodel_name='thoriumcorp.lab.categories',
#        string='Category',
#        help='Category of this lab test'
#    )
    info = fields.Text(
        string='Description'
    )
    product_id = fields.Many2one(
        comodel_name='product.product',
        string='Service',
        required=True
    )
    critearea = fields.One2many(
        comodel_name='thoriumcorp.lab.test.critearea',
        inverse_name='test_type_id',
        string='Test Cases'
    )
    active = fields.Boolean(
        string='Active',
        index=True
    )

    @api.model
    def default_get(self, fields):
        res = super(ThoriumcorpLabTestType, self).default_get(fields)
        res.update(
            {
                'active': True
            }
        )
        return res

    _sql_constraints = [
        (
            'code_uniq',
            'unique(name)',
            'The Lab Test code must be unique'
        )
    ]


class ThoriumcorpLabTestCritearea(models.Model):
    _name = 'thoriumcorp.lab.test.critearea'
    _description = 'Lab Test Critearea'

    test = fields.Boolean(string='Test')
    name = fields.Char(
        string='Analyte',
        required=True,
        index=True,
        translate=True
    )
    excluded = fields.Boolean(
        string='Excluded',
        help='Select this option when this analyte is excluded from the test'
    )
    remarks = fields.Char(
        string='Remarks'
    )
    normal_range = fields.Text(
        string='Reference'
    )
    lower_limit = fields.Float(
        string='Lower Limit'
    )
    upper_limit = fields.Float(
        string='Upper Limit'
    )
    units = fields.Many2one(
        comodel_name='thoriumcorp.lab.test.units',
        string='Units'
    )
    test_type_id = fields.Many2one(
        comodel_name='thoriumcorp.lab.test.type',
        string='Test type',
        index=True
    )
    thoriumcorp_lab_id = fields.Many2one(
        comodel_name='thoriumcorp.lab.test.result',
        string='Test Cases'
#        index=True
    )

    sequence = fields.Integer(
        string='Sequence'
    )

    @api.model
    def default_get(self, fields):
        res = super(ThoriumcorpLabTestCritearea, self).default_get(fields)
        res.update(
            {
                'excluded': False,
                'sequence': 1
            }
        )
        return res
