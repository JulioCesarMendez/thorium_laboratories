#
#    Copyright (C) 2020-2030 Thorium Corp FP <help@thoriumcorp.website>
#

import base64
import collections
import datetime
import hashlib
import pytz
import threading
import re

import requests
from lxml import etree
from werkzeug import urls

from odoo import models, fields, api, tools, SUPERUSER_ID, _
from odoo.modules import get_module_resource
from odoo.osv.expression import get_unaccent_wrapper
from dateutil.relativedelta import relativedelta
from datetime import datetime, timedelta, date
from odoo.exceptions import UserError, ValidationError

#+++++++++++++++++++++++++++++++++++++ incorporated from res.partner ++++++++++++++++++++++++++++++

# Global variables used for the warning fields declared on the thoriumcorp.patient
# in the following modules : sale, purchase, account, stock
WARNING_MESSAGE = [
                   ('no-message','No Message'),
                   ('warning','Warning'),
                   ('block','Blocking Message')
                   ]
WARNING_HELP = 'Selecting the "Warning" option will notify user with the message, Selecting "Blocking Message" will throw an exception with the message and block the flow. The Message has to be written in the next field.'


ADDRESS_FIELDS = ('street', 'street2', 'zip', 'city', 'state_id', 'country_id')
@api.model
def _lang_get(self):
    return self.env['res.lang'].get_installed()


# put POSIX 'Etc/*' entries at the end to avoid confusing users - see bug 1086728
_tzs = [(tz, tz) for tz in sorted(pytz.all_timezones, key=lambda tz: tz if not tz.startswith('Etc/') else '_')]
def _tz_get(self):
    return _tzs

class PatientCategory(models.Model):
    _description = 'Patient Tags'
    _name = 'thoriumcorp.patient.category'
    _order = 'name'

    name = fields.Char(string='Tag Name', required=True, translate=True)
    parent_id = fields.Many2one('thoriumcorp.patient.category', string='Parent Category', index=True, ondelete='cascade')
    category_id = fields.One2many('thoriumcorp.patient.category', 'category_id', string='Child Tags')
    active = fields.Boolean(default=True, help="The active field allows you to hide the category without removing it.")
    category_ids = fields.Many2many('thoriumcorp.patient', column1='category_id', column2='parent_id', string='Categories')

    @api.constrains('category_id')
    def _check_category_id(self):
        if not self._check_recursion():
            raise ValidationError(_('You can not create recursive tags.'))

    def name_get(self):
        """ Return the categories' display name, including their direct
            parent by default.

            If ``context['patient_category_display']`` is ``'short'``, the short
            version of the category name (without the direct parent) is used.
            The default is the long version.
        """
        if self._context.get('patient_category_display') == 'short':
            return super(ThoriumcorpPatientCategory, self).name_get()

        res = []
        for category in self:
            names = []
            current = category
            while current:
                names.append(current.name)
                current = current.category_id
            res.append((category.id, ' / '.join(reversed(names))))
        return res

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        args = args or []
        if name:
            # Be sure name_search is symetric to name_get
            name = name.split(' / ')[-1]
            args = [('name', operator, name)] + args
        patient_category_ids = self._search(args, limit=limit, access_rights_uid=name_get_uid)
        return models.lazy_name_get(self.browse(patient_category_ids).with_user(name_get_uid))


class PatientTitle(models.Model):
    _name = 'thoriumcorp.patient.title'
    _order = 'name'
    _description = 'Patient Title'

    name = fields.Char(string='Title', required=True, translate=True)
    shortcut = fields.Char(string='Abbreviation', translate=True)

#++++++++++++++++++++++++++++++++End of incorporated from res.partner ++++++++++++++++++++++++++++++

class ThoriumcorpPatient(models.Model):
    _description = 'Patient lab tests'
    _name = 'thoriumcorp.patient'
    _sql_constraints = [('id_uniq', 'unique(identity_id)', 'This pacient exists')]

#    def _default_category(self):
#        return self.env['thoriumcorp.patient.category'].browse(self._context.get('category_id'))

    @api.model
    def default_get(self, default_fields):
        """Add the company of the parent as default if we are creating a child patient."""
        values = super().default_get(default_fields)
        if 'identity_id' in default_fields and values.get('identity_id'):
            values['company_id'] = self.browse(values.get('identity_id')).company_id.id
        return values

    identity_id = fields.Char(
        string='C.I. N°:',
        help='Personal Identity Card ID',
        required=True,
        index=True,
    )

    name = fields.Char(
        string='Nombre del paciente:',
        required=True,
        default='New'
    )

#+++++++++++++++++++++++++++++++++++++ incorporated from res.partner ++++++++++++++++++++++++++++++
    register_date = fields.Date(string='Fecha de registro:', value=datetime.today(), index=True)
    title = fields.Many2one('thoriumcorp.patient.title')
    ref = fields.Char(string='Referido por:', index=True)
    lang = fields.Selection(_lang_get, string='Language', default=lambda self: self.env.lang,
                            help="All the emails and documents sent to this contact will be translated in this language.")
    tz = fields.Selection(_tz_get, string='Timezone', default=lambda self: self._context.get('tz'),
                          help="When printing documents and exporting/importing data, time values are computed according to this timezone.\n"
                               "If the timezone is not set, UTC (Coordinated Universal Time) is used.\n"
                               "Anywhere else, time values are computed according to the time offset of your web client.")
    tz_offset = fields.Char(compute='_compute_tz_offset', string='Timezone offset', invisible=True)
    user_id = fields.Many2one('res.users', string='Responsable / Tutor:', help='The internal user in charge of this patient.')
    vat = fields.Char(string='R.I.F.:', help="Registro de Información Fiscal. Rellene el campo con el número de RIF actualizado.", index=True)
    same_vat_patient_id = fields.Many2one('thoriumcorp.patient', string='Pacientes con el mismo RIF:', compute='_compute_same_vat_patient_id', store=False)
    website = fields.Char('Website Link')
    comment = fields.Text(string='Comentarios')
    #category_id = fields.Many2many('thoriumcorp.patient.category', column1='identity_id',
    #                                column2='category_id', string='Tags',)# default=_default_category)
    active = fields.Boolean('Esta Activo?', default=True)
    contient = fields.Boolean('Estado de conciencia?', default=True) 
    employee = fields.Boolean(help="Marque esta casilla si el paciente es un profesional de Salud.")
    function = fields.Char(string='¿Dónde trabaja?:')
    type = fields.Selection(
        [('patient', 'Paciente'),
         ('contact', 'Contacto'),
         ('personal', 'Dirección Personal'),
         ('parent', 'Dirección Familiar'),
         ('other', 'Otra Dirección'),
         ("private", "Dirección Privada"),
        ], string='Tipo de Dirección',
        default='patient',
        help="Dirección en caso de emergencias.")
    street = fields.Char()
    street2 = fields.Char()
    zip = fields.Char(change_default=True)
    city = fields.Char()
    state_id = fields.Many2one("res.country.state", string='Estado', ondelete='restrict', domain="[('country_id', '=?', country_id)]")
    country_id = fields.Many2one('res.country', string='Ciudad', ondelete='restrict')
    patient_latitude = fields.Float(string='Geo Latitude', digits=(16, 5))
    patient_longitude = fields.Float(string='Geo Longitude', digits=(16, 5))
    email = fields.Char()
    email_formatted = fields.Char(
        'Formatted Email', compute='_compute_email_formatted',
        help='Format email address "Name <email@domain>"')
    phone = fields.Char()
    mobile = fields.Char()
    is_company = fields.Boolean(string='Es una Compañía?', default=False,
        help="Check if the contact is a company, otherwise it is a person")
    industry_id = fields.Many2one('thoriumcorp.patient.industry', 'Industry')
    company_type = fields.Selection(string='Tipo de Compañía',
        selection=[('paciente', 'Individual'), ('compañía', 'Compañía')],
        compute='_compute_company_type', inverse='_write_company_type')
    company_id = fields.Many2one('res.company', 'Compañía', index=True)
    company_name = fields.Char('Nombre de Compañía')

    gender = fields.Selection(
        [
            ('male', 'Masculino'),
            ('female', 'Femenino'),
            ('other', 'Otro'),
        ],
        'Genero',
    )
    birthdate_date = fields.Datetime(string='Fecha de Nacimiento:')
    age = fields.Char('Edad:', help="Edad del paciente.")
    deceased = fields.Boolean()
    date_death = fields.Datetime('Fecha de fallecimiento:')
    weight = fields.Float()
    weight_uom = fields.Many2one(
        string="Weight unit",
        comodel_name="uom.uom",
        #domain=lambda self: [(
        #    'category_id', '=',
        #    self.env.ref('uom.product_uom_categ_kgm').id)
        #]
        )
    is_patient = fields.Boolean(
        string='¿Es paciente de este centro?:',
        help='Marque esta casilla si la persona a registrar es un paciente actual de este centro asistencial.'
    )
    unidentified = fields.Boolean(
        string='No identificado:',
        help='El paciente no se ha podido identificar.'
    )
    marital_status = fields.Selection(
        [
            ('s', 'Soltero'),
            ('c', 'Casado'),
            ('v', 'Viudo'),
            ('d', 'Divorciado'),
            ('x', 'Separado')
        ]
    )
    general_info = fields.Text(
        string='Información General',
    )
    is_pregnant = fields.Boolean(
        help='¿Esta embarazada?',
    )
    blood_type = fields.Selection(
        [('A', 'A'), ('B', 'B'), ('AB', 'AB'), ('O', 'O')],
        string='Tipo de Sangre',
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
        'Indicación importante sobre la condición de este paciente.',
        help='Automated summary of patient important medical conditions '
        'other critical information')
    critical_info = fields.Text(
        'Free text information not included in the automatic summary',
        help='Write any important information on the patient\'s condition,'
        ' surgeries, allergies, ...')

    patient_of_medical_center_id = fields.Many2one(
        string='Institución médica:',
        comodel_name='medical.center',
        inverse_name='name',
    )

    lab_test_ids = fields.One2many(
        comodel_name='thoriumcorp.lab.test.requests',
        inverse_name='identity_id',
        string='Exámenes requeridos'
    )

    def _fields_view_get_address(self, arch):
        # consider the country of the user, not the country of the patient we want to display
        address_view_id = self.env.company.country_id.address_view_id
        if address_view_id and not self._context.get('no_address_format'):
            #render the patient address accordingly to address_view_id
            doc = etree.fromstring(arch)
            for address_node in doc.xpath("//div[hasclass('o_address_format')]"):
                Patient = self.env['thoriumcorp.patient'].with_context(no_address_format=True)
                sub_view = Patient.fields_view_get(
                    view_id=address_view_id.id, view_type='form', toolbar=False, submenu=False)
                sub_view_node = etree.fromstring(sub_view['arch'])
                #if the model is different than res.patient, there are chances that the view won't work
                #(e.g fields not present on the model). In that case we just return arch
                if self._name != 'thoriumcorp.patient':
                    try:
                        self.env['ir.ui.view'].postprocess_and_fields(self._name, sub_view_node, None)
                    except ValueError:
                        return arch
                address_node.getparent().replace(address_node, sub_view_node)
            arch = etree.tostring(doc, encoding='unicode')
        return arch

    @api.constrains('is_pregnant', 'gender')
    def _check_is_pregnant(self):
        for record in self:
            if record.is_pregnant and record.gender != 'femenino':
                raise ValidationError(
                    'Invalid selection - Only a female may be pregnant.'
                )

    @api.model
    def _create_vals(self, vals):
        vals.update({
            'name': 'PACIENTE NUEVO',
            'is_company': False,
            'identity_id': 'V-00000001'
        })
        return super(ThoriumcorpPatient, self)._create_vals(vals)

    def patient_blood_info(self):
        self.blood_type = 'A'
        self.rh = '-'
        self.hb = 'aa'

    def toggle_is_pregnant(self):
        self.toggle('is_pregnant')

    def toggle_safety_cap_yn(self):
        self.toggle('safety_cap_yn')

    def toggle_counseling_yn(self):
        self.toggle('counseling_yn')

    @api.depends('tz')
    def _compute_tz_offset(self):
        for patient in self:
            patient.tz_offset = datetime.now(pytz.timezone(patient.tz or 'GMT')).strftime('%z')

    @api.depends('vat')
    def _compute_same_vat_patient_id(self):
        for patient in self:
            # use _origin to deal with onchange()
            identity_id = patient._origin.id
            domain = [('vat', '=', patient.vat)]
            if identity_id:
                domain += [('id', '!=', identity_id), '!', ('id', 'child_of', identity_id)]
            patient.same_vat_patient_id = bool(patient.vat) and not patient.identity_id and self.env['thoriumcorp.patient'].search(domain, limit=1)

    @api.depends(lambda self: self._display_address_depends())
    def _compute_contact_address(self):
        for patient in self:
            patient.contact_address = patient._display_address()

    def _compute_get_ids(self):
        for patient in self:
            patient.self = patient.id

    @api.model
    def _fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        if (not view_id) and (view_type == 'form') and self._context.get('force_email'):
            view_id = self.env.ref('base.view_patient_simple_form').id
        res = super(ThoriumcorpPatient, self)._fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if view_type == 'form':
            res['arch'] = self._fields_view_get_address(res['arch'])
        return res

    def copy(self, default=None):
        self.ensure_one()
        chosen_name = default.get('name') if default else ''
        new_name = chosen_name or _('%s (copy)') % self.name
        default = dict(default or {}, name=new_name)
        return super(ThoriumcorpPatient, self).copy(default)

    @api.onchange('country_id')
    def _onchange_country_id(self):
        if self.country_id and self.country_id != self.state_id.country_id:
            self.state_id = False

    @api.onchange('state_id')
    def _onchange_state(self):
        if self.state_id.country_id:
            self.country_id = self.state_id.country_id

    @api.depends('name', 'email')
    def _compute_email_formatted(self):
        for patient in self:
            if patient.email:
                patient.email_formatted = tools.formataddr((patient.name or u"False", patient.email or u"False"))
            else:
                patient.email_formatted = ''

    @api.depends('is_company')
    def _compute_company_type(self):
        for patient in self:
            patient.company_type = 'compañía' if patient.is_company else 'paciente'

    def _write_company_type(self):
        for patient in self:
            patient.is_company = patient.company_type == 'compañía'

    @api.onchange('company_type')
    def onchange_company_type(self):
        self.is_company = (self.company_type == 'compañía')

    def _update_fields_values(self, fields):
        """ Returns dict of write() values for synchronizing ``fields`` """
        values = {}
        for fname in fields:
            field = self._fields[fname]
            if field.type == 'many2one':
                values[fname] = self[fname].id
            elif field.type == 'one2many':
                raise AssertionError(_('One2Many fields cannot be synchronized as part of `commercial_fields` or `address fields`'))
            elif field.type == 'many2many':
                values[fname] = [(6, 0, self[fname].ids)]
            else:
                values[fname] = self[fname]
        return values

    @api.model
    def _address_fields(self):
        """Returns the list of address fields that are synced from the parent."""
        return list(ADDRESS_FIELDS)

    @api.model
    def _formatting_address_fields(self):
        """Returns the list of address fields usable to format addresses."""
        return self._address_fields()

    def update_address(self, vals):
        addr_vals = {key: vals[key] for key in self._address_fields() if key in vals}
        if addr_vals:
            return super(ThoriumcorpPatient, self).write(addr_vals)

    def _fields_sync(self, values):
        """ Sync commercial fields and address fields from company and to children after create/update,
        just as if those were all modeled as fields.related to the parent """
        # 1. From UPSTREAM: sync from parent
        if values.get('identity_id') or values.get('type') == 'patient':
            # 1a. Commercial fields: sync if parent changed
            if values.get('identity_id'):
                self._commercial_sync_from_company()
            # 1b. Address fields: sync if parent or use_parent changed *and* both are now set
            if self.parent_id and self.type == 'patient':
                onchange_vals = self.onchange_parent_id().get('value', {})
                self.update_address(onchange_vals)

    def _clean_website(self, website):
        url = urls.url_parse(website)
        if not url.scheme:
            if not url.netloc:
                url = url.replace(netloc=url.path, path='')
            website = url.replace(scheme='http').to_url()
        return website



class ResPatientIndustry(models.Model):
    _description = 'Industry'
    _name = "thoriumcorp.patient.industry"
    _order = "name"

    name = fields.Char('Nombre', translate=True)
    full_name = fields.Char('Nombre completo', translate=True)
    active = fields.Boolean('Activo', default=True)

#+++++++++++++++++++++++++++++++++++++ end of incorporated from res.partner +++++++++++++++++++++++

class ThoriumcorpLabTestType(models.Model):
    _inherit = ['mail.thread']
    _inherits = {'lab.product.product': 'product_id'}
    _name = 'thoriumcorp.lab.test.type'
#    _inherit = 'lab.product.product'
    _description = 'Thorium Corp Product model for Type of Lab test'

    def onchange_type(self, _type):
        return self.product_id.onchange_type(_type)

    def onchange_uom(self, uom_id, uom_po_id):
        return self.product_id.onchange_uom(uom_id, uom_po_id)

    def name_get(self):
        res = []
        for rec in self:
            name = '%s' % (rec.product_id.name)
            res.append((rec.id, name))
        return res

    product_id = fields.Many2one(
        comodel_name='lab.product.product',
        string='Test',
        required=True,
        ondelete="cascade"
    )

    @api.model
    @api.returns('self', lambda value: value.id)
    def create(self, vals):
        #vals['test_type'] = self.env['name']
        return super(ThoriumcorpLabTestType, self).create(vals)

class ThoriumcorpPatientLabTest(models.Model):
    _name = 'thoriumcorp.lab.test.requests'
    _description = 'Patient Lab Test'
    _sql_constraints = [(
        'thoriumcorp_lab_test_unique_request_code',
        'UNIQUE (name)',
        'Internal ID must be unique',
    )]

    name = fields.Char(
        string='Solicitud',
        readonly=False,
        required=True,
        copy=False,
        default=lambda s: s.env['ir.sequence'].next_by_code(s._name + '.name')
    )

    identity_id = fields.Many2one(
        comodel_name='thoriumcorp.patient',
        string='Paciente',
        inverse_name='identity_id',
        required=True,
        index=True
    )
    test_type = fields.Many2one(
        comodel_name='thoriumcorp.lab.test.type',
        string='Tipo de Exámen',
        required=True,
        index=True
    )
    date = fields.Datetime(
        string='Fecha',
        required=True,
        index=True
    )
    state = fields.Selection(
        [
            ('draft', 'Borrador'),
            ('tested', 'Realizado'),
            ('ordered', 'Ordenado'),
            ('cancel', 'Cancelado'),
        ],
        string='Estado',
        default='draft',
        readonly=False,
        index=True
    )
    referenced_by = fields.Many2one(
        string='Centro Médico',
        comodel_name='medical.center',
        inverse_name='name',
    )
    urgent = fields.Boolean(
        string='Urgente'
    )
    test_result = fields.One2many(
        comodel_name='thoriumcorp.lab.test.result',
        inverse_name='name',
        string='Resultado'
    )
    result_count = fields.Char(
        string='Resultados'
    )

    requestor = fields.Many2one(
        comodel_name='thoriumcorp.practitioner',
        string='Especialista',
        help="Doctor que ordenó el exámen",
    )

#    critearea = fields.One2many(
#        comodel_name='thoriumcorp.lab.test.critearea',
#        inverse_name='test_type_id',
#        string='Parámetros del Exámen'
#    )
    value = fields.One2many(
        comodel_name='thoriumcorp.lab.test.value',
        inverse_name='test_result',
        string='Resultados',
    )
    date_analysis = fields.Datetime(
        string='Fecha del Análisis',
        index=True,
        default=datetime.now(),
        readonly=True,
    )
    analytes_summary = fields.Text(
        string='Resumen'
    )

    def get_result(self):
        self.ensure_one()
        result_id = self.test_result.id
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
                'default_test_request': self.name.id,
                #'default_test_code': self.code.id,
                'default_patient': self.identity_id.id,
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
        date_time = fields.Datetime.now()
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code(self._name) or 'TST' + date_time.strftime('%Y%m%d%H%M%S')
#            vals['pay_ref'] = vals['name']
        return super(ThoriumcorpPatientLabTest, self).create(vals)

#    @api.onchange('test_type')
#    def onchange_test_type(self):
#        if self.test_type:
#            self.critearea = self.test_type.critearea

class ThoriumcorpLabTestResult(models.Model):
    _name = 'thoriumcorp.lab.test.result'
    _description = 'Lab Test Results'
    _inherit = ['thoriumcorp.lab.test.requests']

    name = fields.Many2one(
        comodel_name='thoriumcorp.lab.test.requests',
        string='Exámen Requerido',
        required=True,
    )

    identity_id = fields.Many2one(
        string='Paciente',
    )

    test_type = fields.Many2one(
        string='Tipo de Exámen',
    )

    date = fields.Datetime(
        string='Fecha',
        required=True,
        readonly=True,
    )
    state = fields.Selection(
        string='Estado',
        required=True,
    )
    urgent = fields.Boolean(
        string='Urgente',
    )
    value = fields.One2many(
        comodel_name='thoriumcorp.lab.test.value',
        inverse_name='test_result',
        string='Resultados',
    )

    requestor = fields.Many2one(
        string='Especialista',
        help="Doctor quien solicitó el exámen",
        index=True,
        readonly=True,
    )

#    critearea = fields.One2many(
#        comodel_name='thoriumcorp.lab.test.critearea',
#        inverse_name='test_type_id',
#        string='Parámetros del Exámen',
#    )

    date_analysis = fields.Datetime(
        string='Fecha del Análisis',
        index=True,
        default=datetime.now(),
        readonly=True,
    )
    analytes_summary = fields.Text(
        string='Resumen'
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

    _sql_constraints = [
        (
            'id_uniq',
            'unique(name)',
            'El ID del exámen debe ser único'
        )
    ]

    @api.model
    def create(self, vals):
        if self.name:
            self.identity_id = self.name.identity_id
            self.date = self.name.date
            self.test_type = self.name.test_type
            self.state = self.name.state
            self.urgent = self.name.urgent
            self.value = self.name.value
            self.requestor = self.name.requestor
            self.critearea = self.name.critearea
            self.date_analysis = self.name.date_analysis
            self.analytes_summary = self.name.analytes_summary
            #value_ids = self.name.critearea.filtered(
            #    lambda r: not r.test_type_id
            #)
            #if not value_ids:
            #    raise ValidationError(_('BAN001 No hay valores en critearea...'))
            #self.critearea = [
            #    (0, 0, {
            #        'sequence': line.sequence,
            #        'name': line.name,
            #        'excluded': line.excluded,
            #        'remarks': line.remarks,
            #        'normal_range': line.normal_range,
            #        'lower_limit': line.lower_limit,
            #        'upper_limit': line.upper_limit,
            #        'units': line.units
            #    }) for line in value_ids
            #]
        return super(ThoriumcorpLabTestResult, self).create(vals)

    def write(self, vals):
        for record in self:
            record.write
        super(ThoriumcorpLabTestResult, self).write(vals)

    @api.onchange('test_type')
    def onchange_test_type(self):
        #if self.test_type:
        #    self.critearea = self.test_type.critearea
        for record in self:
            record.write

    @api.onchange('name')
    def on_change_name(self):
        if self.name:
            self.identity_id = self.name.identity_id
            self.date = self.name.date
            self.test_type = self.name.test_type
            self.state = self.name.state
            self.urgent = self.name.urgent
            self.value = self.name.value
            self.requestor = self.name.requestor
            #self.critearea = self.name.critearea
            self.date_analysis = self.name.date_analysis
            self.analytes_summary = self.name.analytes_summary
        for record in self:
            record.write

# ToDo: Modificar para que cuando se fije el valor se active el "warning del value" si es requerido
#    @api.onchange('value')
#    def on_change_value(self):
#        if self.value.result > self.critearea...:
#            self.value = self.name.value

    def button_progress(self):
        for record in self:
            record.write({
                        'state': 'en_progreso'
                        })

    def button_close(self):
        for record in self:
            record.write({
                        'state': 'cerrado'
                        })

    def button_cancelled(self):
        for record in self:
            record.write({
                        'state': 'cancelado'
                        })

    def button_draft(self):
        for record in self:
            record.write({
                        'state': 'draft'
                        })

class ThoriumcorpLabTestValue(models.Model):
    _name = 'thoriumcorp.lab.test.value'
    _description = 'Lab Test Result Value'

    test_result = fields.Many2one(
        comodel_name='thoriumcorp.lab.test.result',
        string='Resultado del Exámen'
    )
    result = fields.Float(
        string='Valor'
    )
    result_text = fields.Char(
        string='Resultado (Texto)',
        help='Detalle descriptivo. Para'
        'valores cualitativos del exámen, morfología, color ...'
    )
    warning = fields.Boolean(
        string='Alerta',
        help='Alertar al paciente sobre su'
        ' resultado de análisis'
        ' Es útil para contextualizar el resultado para cada pacientes, como stado,'
        ' edad, sexo, comorbidities, ...'
    )


class ThoriumcorpLabTestUnits(models.Model):
    _name = 'thoriumcorp.lab.test.units'
    _description = 'Lab Test Units'

    name = fields.Char(
        string='Unidad',
        index=True
    )
    code = fields.Char(
        string='Código',
        index=True
    )

    _sql_constraints = [
        (
            'name_uniq',
            'unique(name)',
            'The Unit name must be unique'
        ),
        (
            'code_uniq',
            'unique(code)',
            'The Unit code must be unique'
        )
    ]


class ThoriumcorpLabTestCritearea(models.Model):
    _name = 'thoriumcorp.lab.test.critearea'
    _description = 'Lab Test Critearea'
# ********************************************************************
# Es posible que un mismo criterio sirva para varios tipos de examenes
# ********************************************************************

#    test_type_id = fields.Many2one(
#        comodel_name='thoriumcorp.lab.test.type',
#        string='Test type',
#        index=True
#    )

    sequence = fields.Integer(
        string='Secuencia',
        index=True,
        default=lambda s: s.env['ir.sequence'].next_by_code(s._name)
    )

    name = fields.Char(
        string='Análisis',
        required=True,
        index=True,
        translate=True
    )
    excluded = fields.Boolean(
        string='Excluído',
        help='Select this option when this analyte is excluded from the test'
    )
    remarks = fields.Char(
        string='Remarks'
    )
    normal_range = fields.Text(
        string='Referencia'
    )
    lower_limit = fields.Float(
        string='Limit Inferior'
    )
    upper_limit = fields.Float(
        string='Limit Superior'
    )
    units = fields.Many2one(
        comodel_name='thoriumcorp.lab.test.units',
        string='Unidades'
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

    @api.model
    def create(self, vals):
        #if vals.get('secuence', _('New')) == _('New'):
        #    vals['secuence'] = self.env['ir.sequence'].next_by_code(self._name)
        return super(ThoriumcorpLabTestCritearea, self).create(vals)

class ThoriumcorpRole(models.Model):
    _name = 'thoriumcorp.role'
    _description = 'Practitioner Roles'

    name = fields.Char(required=True,)
    description = fields.Char(required=True,)
    active = fields.Boolean(default=True,)

class ThoriumcorpSpecialty(models.Model):
    _name = 'thoriumcorp.specialty'
    _description = 'Medical Specialty'
    _sql_constraints = [
        ('code_uniq', 'UNIQUE(code)', 'Code must be unique!'),
        ('name_uniq', 'UNIQUE(name)', 'Name must be unique!'),
    ]

    code = fields.Char(
        string='Código',
        help='Speciality code',
        size=256,
        required=True,
    )
    name = fields.Char(
        string='Nombre',
        help='Name of the specialty',
        size=256,
        required=True,
    )
    category = fields.Selection(
        [
            ('clinical', 'Especialidades Clinicas'),
            ('surgical', 'Especialties Quirúrgicas'),
            ('medical', 'Especialidades Medica-quirurgicas'),
            ('diagnostic', 'Especilidades de Laboratorio y diagnósticos'),
        ],
        'Categoria de especialidades'
    )

class MedicalCenter(models.Model):
    _name = 'medical.center'
    _description = 'Centro Médico'
    _sql_constraints = [('code_uniq', 'unique(code)', 'This code exists')]

    code = fields.Char(
        'Código',
        required=True,
    )
    name = fields.Char(
        'Nombre',
        required=True,
        index=True,
    )
    institution_type = fields.Selection(
        [
            ('doctor_office', 'Consultorio Particular'),
            ('primary_care', 'Centro de atención Primaria'),
            ('clinic', 'Clínica'),
            ('hospital', 'Hospital General'),
            ('uch', 'Hospital Clínico Universitario'),
            ('specialized', 'Hospital Especializado'),
            ('nursing_home', 'Casa de cuidados'),
            ('hospice', 'Hospice'),
            ('rural', 'Instalación Rural'),
            ('ba1', 'Barrio Adentro I'),
            ('ba2', 'Barrio Adentro II'),
            ('ba3', 'Barrio Adentro III'),
            ('pasi', 'PASI'),
            ('cat', 'CAT'),
            ('cdi', 'CDI'),
            ('cri', 'CRI'),
        ],
        'Tipo',
        required=True,
        sort=True,
    )
    beds = fields.Integer("Camas")
    operating_room = fields.Boolean(
        "Quirófanos",
        help="Does the institution have an operating room?",
    )
    or_number = fields.Integer("Operating rooms")
    public_level = fields.Selection(
        [
            ('public', 'Público'),
            ('private', 'Privado'),
            ('mixed', 'Mixto'),
        ],
        'Nivel Público',
        required=True,
        sort=False
    )
    teaching = fields.Boolean(
        "Universitario",
        help="Is it a teaching institution?"
    )
    heliport = fields.Boolean("Helipuerto")
    trauma_center = fields.Boolean("Sala de Trauma Chock")
    trauma_level = fields.Selection(
        [
            ('I', 'Level I'),
            ('II', 'Level II'),
            ('III', 'Level III'),
            ('IV', 'Level IV'),
            ('V', 'Level V'),
        ],
        'Nivel de atención de Trauma',
        sort=False
    )
    extra_info = fields.Text("Información Adicional")
    specialties = fields.One2many(
        'institution.specialties',
        'name',
        'Especialidades',
        help="Specialties Provided in this Medical Institution"
    )
    main_specialty = fields.Many2one(
        'institution.specialties',
        'Especialidad Principal',
        help="Main specialty, for specialized hospitals",
    )
    operational_sectors = fields.One2many(
        'institution.operationalsector',
        'name',
        'Sector Operacional',
        help="Operational Sectors covered by this institution"
    )

    @api.model
    def _create_vals(self, vals):
        vals.update({
            'is_company': True,
            'medical_type': 'medical_center'
        })
        return super(MedicalCenter, self)._create_vals(vals)

    def _get_default_image_path(self, vals):
        super(MedicalCenter, self)._get_default_image_path(vals)
        return get_module_resource(
            'medical_center', 'static/src/img', 'medical-center-avatar.png',
        )

class MedicalInstitutionSpecialties(models.Model):
    _name = 'institution.specialties'
    _description = 'Institución de Especialidades Medicas'

    name = fields.Many2one(
        'medical.center',
        'Institución',
        inverse_name='code',
        required=True,
    )
    specialty = fields.Many2one(
        'thoriumcorp.specialty',
        'Specialty',
        required=True
    )

    _sql_constraints = [(
        'name_sp_uniq',
        'unique(name, specialty)',
        'This specialty exists for this institution'
    )]

    def get_rec_name(self, name):
        if self.specialty:
            return self.specialty.name


class MedicalInstitutionOperationalSector(models.Model):
    _name = 'institution.operationalsector'
    _description = 'Sector Operacional Cubiertos Por Esta Institución'

    name = fields.Many2one(
        'medical.center',
        'Institución',
        inverse_name='code',
        required=True,
    )

class Building(models.Model):
    _name = 'building'
    _description = 'Hospital Building'

    name = fields.Char(
        'Name',
        required=True,
        help='Name of the building within the institution'
    )
    institution = fields.Many2one(
        'medical.center',
        'Institución',
        required=True,
        inverse_name='code',
        help='Medical Institution of this building',
    )
    code = fields.Char('Code', required=True)
    extra_info = fields.Text('Additiona information')

    _sql_constraints = [
        (
            'name_uniq',
            'unique(name, institution)',
            'The building name must be unique'
        ), (
            'code_uniq',
            'unique(code, institution)',
            'The building code must be unique'
        )
    ]


class HospitalUnit(models.Model):
    _name = 'hospital.unit'
    _description = 'Unidad Hospitalaria'

    name = fields.Char(
        'Nombre',
        required=True,
        help='Name of the unit, eg. Neonatal, Intensive Care ...'
    )
    institution = fields.Many2one(
        'medical.center',
        'Institución',
        required=True,
        inverse_name='code',
        help='Medical Institution',
    )
    code = fields.Char('Code', required=True)
    extra_info = fields.Text('Additional information')

    _sql_constraints = [
        (
            'name_uniq',
            'unique(name, institution)',
            'The Unit name must be unique'
        ), (
            'code_uniq',
            'unique(code, institution)',
            'The Unit code must be unique'
        )
    ]


class HospitalOR(models.Model):
    _name = 'hospital.or'
    _description = 'Quirófanos'

    name = fields.Char(
        'Name',
        required=True,
        help='Operating room name'
    )
    institution = fields.Many2one(
        'medical.center',
        'Institución',
        required=True,
        inverse_name='code',
        help='Medical Institution',
    )
    building = fields.Many2one(
        'building',
        'Building'
    )
    unit = fields.Many2one('hospital.unit', 'Unit')
    extra_info = fields.Text('Additional Info')
    state = fields.Selection(
        [
            ('free', 'Free'),
            ('confirmed', 'Confirmed'),
            ('occupied', 'Occupied'),
            ('na', 'Not available'),
        ],
        'Status',
        readonly=True,
        sort=False
    )

    _sql_constraints = [
        (
            'name_uniq',
            'unique(name, institution)',
            'This name exists for this unit'
        ),
    ]

    def default_state():
        return 'free'


class HospitalWard(models.Model):
    _name = 'hospital.ward'
    _description = 'Hospital Ward'

    name = fields.Char(
        'name',
        required=True,
        help='Ward name/code'
    )
    institution = fields.Many2one(
        'medical.center',
        'Institución',
        inverse_name='code',
        required=True,
    )
    building = fields.Many2one(
        'building',
        'Building'
    )
    floor = fields.Integer('Floor number')
    unit = fields.Many2one('hospital.unit', 'Unit')
    private = fields.Boolean(
        'Private',
        help='Check this option for private room'
    )
    bio_hazard = fields.Boolean(
        'Bio Hazard',
        help='Check this option if there is biological hazard'
    )
    number_of_beds = fields.Integer(
        'Number of beds',
        help='Number of patients per ward'
    )
    telephone = fields.Boolean('Telephone access')
    ac = fields.Boolean('Air Conditioning')
    private_bathroom = fields.Boolean('Private Bathroom')
    guest_sofa = fields.Boolean('Guest sofa-bed')
    tv = fields.Boolean('Television')
    internet = fields.Boolean('Internet Access')
    refrigerator = fields.Boolean('Refrigerator')
    microwave = fields.Boolean('Microwave')
    gender = fields.Selection(
        [
            ('men', 'Men\'s ward'),
            ('women', 'Women\'s ward'),
            ('unisex', 'Unisex'),
        ],
        'Gender',
        required=True,
        default='unisex',
        sort=False
    )
    state = fields.Selection(
        [
            ('beds_available', 'Beds available'),
            ('full', 'Full'),
            ('na', 'Not available'),
        ],
        'Status',
        sort=False
    )
    extra_info = fields.Text('Inf. Extra')

    _sql_constraints = [
        (
            'name_uniq',
            'unique(name, institution)',
            'The Ward / Room Name must be unique'
        ),
    ]

class HospitalBed(models.Model):
    _name = 'hospital.bed'
    _rec_name = 'telephone_number'
    _description = 'Cama de Hospital'

    name = fields.Many2one(
        'product.product',
        'Bed',
        required=True,
        help='Bed Number'
    )
    institution = fields.Many2one(
        'medical.center',
        'Institución',
        required=True,
        inverse_name='code',
        help='Medical institution'
    )
    ward = fields.Many2one(
        'hospital.ward',
        'Ward'
    )
    bed_type = fields.Selection(
        [
            ('gatch', 'Gatch bed'),
            ('electric', 'Electric'),
            ('stretcher', 'Stretcher'),
            ('low', 'Low bed'),
            ('low_air_loss', 'Low air loss'),
            ('circo_electric', 'Circo Electric'),
            ('clinitron', 'Clinitron'),
        ],
        'Bed type',
        required=True,
        sort=False
    )
    telephone_number = fields.Char(
        'Phone number',
        help='Number/Extention'
    )
    extra_info = fields.Text('Additional information')
    state = fields.Selection(
        [
            ('free', 'free'),
            ('reserved', 'Reserved'),
            ('occupied', 'Occupied'),
            ('to_clean', 'To be cleaned'),
            ('na', 'Not available'),
        ],
        'State',
        readonly=True,
        sort=False
    )

    _sql_constraints = [
        (
            'name_uniq',
            'unique(name, institution)',
            'The bed must be unique'
        )
    ]

    def default_bed_type():
        return 'gatch'

    def default_state():
        return 'free'

    def get_rec_name(self, name):
        if self.name:
            return self.name.name

    def search_rec_name(self, name, clause):
        return [('name',) + tuple(clause[1:])]


class MedicalAbstractEntity(models.AbstractModel):
    _name = 'medical.abstract_entity'
    _description = 'Thorium Corp Medical Center Abstract Entity'
    _inherits = {'thoriumcorp.patient': 'partner_id'}
    _inherit = ['mail.thread']

    partner_id = fields.Many2one(
        comodel_name='thoriumcorp.patient',
        required=True,
#        ondelete="cascade",
    )
    @api.model
    @api.returns('self', lambda value: value.id)
    def create(self, vals):
        return super(ThoriumcorpPatient, self).create(vals)

    def toggle_active(self):
        """ It toggles patient and partner activation. """
        for record in self:
            super(ThoriumcorpPatient, self).toggle_active()
            if record.active:
                record.partner_id.active = True
            else:
                entities = record.env[record._name].search([
                    ('partner_id', 'child_of', record.partner_id.id),
                    ('active', '=', True),
                ])
                if not entities:
                    record.partner_id.active = False

    def toggle(self, attr):
        if getattr(self, attr) is True:
            self.write({attr: False})
        elif getattr(self, attr) is False:
            self.write({attr: True})

class ThoriumcorpPractitioner(models.Model):
    _name = 'thoriumcorp.practitioner'
    _description = 'Thorium Corp Practitioner'
    _inherit = 'medical.abstract_entity'
    _sql_constraints = [(
        'thoriumcorp_practitioner_unique_code',
        'UNIQUE (code)',
        'Internal ID must be unique',
    )]

    thoriumcorp_center_primary_id = fields.Many2one(
        string='Primary thoriumcorp center',
        comodel_name='medical.center',
        inverse_name='name',
    )
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

