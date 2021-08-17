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
    _parent_store = True

    name = fields.Char(string='Tag Name', required=True, translate=True)
    color = fields.Integer(string='Color Index')
    parent_id = fields.Many2one('thoriumcorp.patient.category', string='Parent Category', index=True, ondelete='cascade')
    category_id = fields.One2many('thoriumcorp.patient.category', 'category_id', string='Child Tags')
    active = fields.Boolean(default=True, help="The active field allows you to hide the category without removing it.")
    parent_path = fields.Char(index=True)
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

    def _default_category(self):
        return self.env['thoriumcorp.patient.category'].browse(self._context.get('category_id'))

    @api.model
    def default_get(self, default_fields):
        """Add the company of the parent as default if we are creating a child patient."""
        values = super().default_get(default_fields)
        if 'identity_id' in default_fields and values.get('identity_id'):
            values['company_id'] = self.browse(values.get('identity_id')).company_id.id
#        if 'parent_id' in default_fields and values.get('parent_id'):
#            values['company_id'] = self.browse(values.get('parent_id')).company_id.id
        return values

    def _split_street_with_params(self, street_raw, street_format):
        return {'street': street_raw}

    identity_id = fields.Char(
        string='C.I. N°:',
        help='Personal Identity Card ID',
        index=True
    )

#    patient_id = fields.Many2one(
#        comodel_name='thoriumcorp.patient',
#        string='Paciente:',
#        required=True,
#        index=True
#    )

    name = fields.Char(
        string='Nombre del paciente:',
#        readonly=False,
        required=True,
        default='New'
    )

    identification_code = fields.Char(
        string='Identificación interna:',
        help='Identificación del paciente provista por el centro de salud',
    )

    alias = fields.Char(
        string='Alias:',
        help='Common, not official, name',
    )

#+++++++++++++++++++++++++++++++++++++ incorporated from res.partner ++++++++++++++++++++++++++++++
#    display_name = fields.Char(compute='_compute_display_name', string='Nombre a mostrar:', index=True)
#    display_name = fields.Char(compute='_compute_display_name', store=True, index=True)
    register_date = fields.Date(string='Fecha de registro:', value=datetime.today(), index=True)
    title = fields.Many2one('thoriumcorp.patient.title')
#    parent_id = fields.Many2one('thoriumcorp.patient', string='Related Company', index=True)
#    parent_id = fields.Many2one('thoriumcorp.patient', string='Related Company', index=True)
#    parent_id.name = fields.Char(related='parent_id', string='Parent name')
#    parent_id.name = fields.Char(related='parent_id', readonly=True, string='Parent name')
#    child_ids = fields.One2many('thoriumcorp.patient', 'parent_id', string='Contact', domain=[('active', '=', True)])  # force "active_test" domain to bypass _search() override
    ref = fields.Char(string='Referido por:', index=True)
    lang = fields.Selection(_lang_get, string='Language', default=lambda self: self.env.lang,
                            help="All the emails and documents sent to this contact will be translated in this language.")
#    active_lang_count = fields.Integer(compute='_compute_active_lang_count')
    tz = fields.Selection(_tz_get, string='Timezone', default=lambda self: self._context.get('tz'),
                          help="When printing documents and exporting/importing data, time values are computed according to this timezone.\n"
                               "If the timezone is not set, UTC (Coordinated Universal Time) is used.\n"
                               "Anywhere else, time values are computed according to the time offset of your web client.")

    tz_offset = fields.Char(compute='_compute_tz_offset', string='Timezone offset', invisible=True)
    user_id = fields.Many2one('res.users', string='Responsable / Tutor:', help='The internal user in charge of this patient.')
    vat = fields.Char(string='R.I.F.:', help="Registro de Información Fiscal. Rellene el campo con el número de RIF actualizado.")
    same_vat_patient_id = fields.Many2one('thoriumcorp.patient', string='Pacientes con el mismo RIF:', compute='_compute_same_vat_patient_id', store=False)
#    bank_ids = fields.One2many('res.partner.bank', 'partner_id', string='Banks')
    website = fields.Char('Website Link')
    comment = fields.Text(string='Notes')

#    category_id = fields.Many2many('thoriumcorp.patient.category', column1='patient_id',
    category_id = fields.Many2many('thoriumcorp.patient.category', column1='identity_id',
                                    column2='category_id', string='Tags', default=_default_category)
#    credit_limit = fields.Float(string='Credit Limit')
    active = fields.Boolean(default=True)
    employee = fields.Boolean(help="Marque esta casilla si el paciente es un profesional de Salud.")
    function = fields.Char(string='¿Dónde trabaja?:')
    type = fields.Selection(
        [('contact', 'Contact'),
         ('personal', 'Personal Address'),
         ('parent', 'Parent Address'),
         ('other', 'Other Address'),
         ("private", "Private Address"),
        ], string='Address Type',
        default='contact',
        help="Dirección en caso de emergencias.")
    street = fields.Char()
    street2 = fields.Char()
    zip = fields.Char(change_default=True)
    city = fields.Char()
    state_id = fields.Many2one("res.country.state", string='State', ondelete='restrict', domain="[('country_id', '=?', country_id)]")
    country_id = fields.Many2one('res.country', string='Country', ondelete='restrict')
    patient_latitude = fields.Float(string='Geo Latitude', digits=(16, 5))
    patient_longitude = fields.Float(string='Geo Longitude', digits=(16, 5))
    email = fields.Char()
    email_formatted = fields.Char(
        'Formatted Email', compute='_compute_email_formatted',
        help='Format email address "Name <email@domain>"')
    phone = fields.Char()
    mobile = fields.Char()
    is_company = fields.Boolean(string='Is a Company', default=False,
        help="Check if the contact is a company, otherwise it is a person")
    industry_id = fields.Many2one('thoriumcorp.patient.industry', 'Industry')
    # company_type is only an interface field, do not use it in business logic
    company_type = fields.Selection(string='Company Type',
        selection=[('person', 'Individual'), ('company', 'Company')],
        compute='_compute_company_type', inverse='_write_company_type')
    company_id = fields.Many2one('res.company', 'Company', index=True)
#    color = fields.Integer(string='Color Index', default=0)
#    user_ids = fields.One2many('res.users', 'partner_id', string='Users', auto_join=True)
#    patient_share = fields.Boolean(
#        'Share Patient', compute='_compute_patient_share', store=True,
#        help="Either customer (not a user), either shared user. Indicated the current patient is a customer without "
#             "access or with a limited access created for sharing data.")
#    contact_address = fields.Char(compute='_compute_contact_address', string='Complete Address')
#
#    # technical field used for managing commercial fields
#    partner_id = fields.Many2one(string='Related Partner', comodel_name='thoriumcorp.patient', required=True, 
#                                             ondelete='cascade', store=True, index=True)
#    commercial_patient_id = fields.Many2one('thoriumcorp.patient', compute='_compute_commercial_patient',
#                                             string='Commercial Entity', store=True, index=True)
#    commercial_company_name = fields.Char('Company Name Entity', compute='_compute_commercial_company_name',
#                                          store=True)
    company_name = fields.Char('Company Name')

    # fields for medical use
# ****************************************************************************************

#    patient_ids = fields.One2many(
#        string='¿Tiene familiares como pacientes actualmente?:',
#        comodel_name='thoriumcorp.patient',
#        # compute='_compute_patient_ids_and_count',
#        inverse_name='partner_id',
#    )

#    count_patients = fields.Integer(compute='_count_patients')

    gender = fields.Selection(
        [
            ('male', 'Male'),
            ('female', 'Female'),
            ('other', 'Other'),
        ],
        'Gender',
    )
    birthdate_date = fields.Datetime(string='Fecha de Nacimiento:')
    age = fields.Char('Edad:', help="Edad del paciente.")
    deceased = fields.Boolean()
    date_death = fields.Datetime('Fecha de fallecimiento:')
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
        string='¿Es paciente?:',
        help='Marque esta casilla si la persona a registrar es un paciente.'
    )
#    is_healthprof = fields.Boolean(
#        string='Profesional de Salud',
#        help='Marque si es profesional de salud'
#    )
    unidentified = fields.Boolean(
        string='No identificado:',
        help='El paciente no se ha podido identificar.'
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
#    referenced_by = fields.Selection([('medical_center', 'Medical Center')]) 
#    referenced_by = fields.Many2one('res.company', 'Insitutión Médica', index=True)
# ****************************************************************************************

    # all image fields are base64 encoded and PIL-supported

#    image1920 = fields.Image("Image", max_width=1920, max_height=1920)

    # resized fields stored (as attachment) for performance
#    image_1024 = fields.Image("Image 1024", related="image1920", max_width=1024, max_height=1024, store=True)
#    image_512 = fields.Image("Image 512", related="image1920", max_width=512, max_height=512, store=True)
#    image_256 = fields.Image("Image 256", related="image1920", max_width=256, max_height=256, store=True)
#    image_128 = fields.Image("Image 128", related="image1920", max_width=128, max_height=128, store=True)

#+++++++++++++++++++++++++++++++++++++ end of incorporated from res.partner +++++++++++++++++++++++


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
        string='Institución médica:',
        comodel_name='medical.center',
    )

    lab_test_ids = fields.One2many(
        comodel_name='thoriumcorp.lab.test.requests',
        inverse_name='identity_id',
#        inverse_name='patient_id', identity_id
        string='Lab Tests Required'
    )

    # fields for medical use
# ****************************************************************************************

    # hack to allow using plain browse record in qweb views, and used in ir.qweb.field.contact
    self = fields.Many2one(comodel_name=_name, compute='_compute_get_ids')

    _sql_constraints = [
        ('check_name', "CHECK( (type='contact' AND name IS NOT NULL) or (type!='contact') )", 'Contacts require a name'),
    ]

#+++++++++++++++++++++++++++++++++++++ end of incorporated from res.partner +++++++++++++++++++++++

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
            if record.is_pregnant and record.gender != 'female':
                raise ValidationError(
                    'Invalid selection - Only a female may be pregnant.'
                )

#    @api.model
#    def _create_vals(self, vals):
#        vals = super(ThoriumcorpPatient, self)._create_vals(vals)
#        if not vals.get('identification_code'):
#            Seq = self.env['ir.sequence']
#            vals['identification_code'] = Seq.sudo().next_by_code(
#                self._name,
#            )
        # vals.update({
        #     'customer': True,
        # })
#        return vals

    @api.model
    def create(self, vals):
#       if vals.get('name', 'New') == 'New':
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code(self._name) or 'New'
        return super(ThoriumcorpPatient, self).create(vals)

#    @api.model_create_multi
#    def create(self, vals_list):
#        if self.env.context.get('import_file'):
#            self._check_import_consistency(vals_list)
#        for vals in vals_list:
#            if vals.get('website'):
#                vals['website'] = self._clean_website(vals['website'])
#            if vals.get('parent_id'):
#                vals['company_name'] = False
#        patients = super(ThoriumcorpPatient, self).create(vals_list)
#
#        if self.env.context.get('_patients_skip_fields_sync'):
#            return patients
#
#        for patient, vals in zip(patients, vals_list):
#            patient._fields_sync(vals)
#            patient._handle_first_contact_creation()
#        return patients




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


#+++++++++++++++++++++++++++++++++++++ Incorporated from res.partner +++++++++++++++++++++++
    def init(self):
        self._cr.execute("""SELECT indexname FROM pg_indexes WHERE indexname = 'patient_vat_index'""")
        if not self._cr.fetchone():
            self._cr.execute("""CREATE INDEX patient_vat_index ON thoriumcorp_patient (regexp_replace(upper(vat), '[^A-Z0-9]+', '', 'g'))""")

#    @api.depends('is_company', 'name', 'parent_id.display_name', 'type', 'company_name')
#    def _compute_display_name(self):
#        diff = dict(show_address=None, show_address_only=None, show_email=None, html_format=None, show_vat=None)
#        names = dict(self.with_context(**diff).name_get())
#        for patient in self:
#            patient.display_name = names.get(patient.id)

#    @api.depends('lang')
#    def _compute_active_lang_count(self):
#        lang_count = len(self.env['res.lang'].get_installed())
#        for patient in self:
#            patient.active_lang_count = lang_count

    @api.depends('tz')
    def _compute_tz_offset(self):
        for patient in self:
            patient.tz_offset = datetime.now(pytz.timezone(patient.tz or 'GMT')).strftime('%z')

#    @api.depends('user_ids.share', 'user_ids.active')
#    def _compute_patient_share(self):
#        super_patient = self.env['thoriumcorp.patient'].browse(SUPERUSER_ID).patient_id
#        if super_patient in self:
#            super_patient.patient_share = False
#        for patient in self - super_patient:
#            patient.patient_share = not patient.user_ids or not any(not user.share for user in patient.user_ids)

    @api.depends('vat')
    def _compute_same_vat_patient_id(self):
        for patient in self:
            # use _origin to deal with onchange()
#            patient_id = patient._origin.id
#            domain = [('vat', '=', patient.vat)]
#            if patient_id:
#                domain += [('id', '!=', patient_id), '!', ('id', 'child_of', patient_id)]
#            patient.same_vat_patient_id = bool(patient.vat) and not patient.parent_id and self.env['thoriumcorp.patient'].search(domain, limit=1)
            identity_id = patient._origin.id
            domain = [('vat', '=', patient.vat)]
            if identity_id:
                domain += [('id', '!=', identity_id), '!', ('id', 'child_of', identity_id)]
            patient.same_vat_patient_id = bool(patient.vat) and not patient.identity_id and self.env['thoriumcorp.patient'].search(domain, limit=1)
#            patient.same_vat_patient_id = bool(patient.vat) and not patient.parent_id and self.env['thoriumcorp.patient'].search(domain, limit=1)

    @api.depends(lambda self: self._display_address_depends())
    def _compute_contact_address(self):
        for patient in self:
            patient.contact_address = patient._display_address()

    def _compute_get_ids(self):
        for patient in self:
            patient.self = patient.id

#    @api.depends('is_company', 'parent_id.commercial_patient_id')
#    def _compute_commercial_patient(self):
#        for patient in self:
#            if patient.is_company or not patient.parent_id:
#                patient.commercial_patient_id = patient
#            else:
#                patient.commercial_patient_id = patient.parent_id.commercial_patient_id

#    @api.depends('company_name', 'parent_id.is_company', 'commercial_patient_id.name')
#    def _compute_commercial_company_name(self):
#        for patient in self:
#            p = patient.commercial_patient_id
#            patient.commercial_company_name = p.is_company and p.name or patient.company_name

    @api.model
    def _fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        if (not view_id) and (view_type == 'form') and self._context.get('force_email'):
            view_id = self.env.ref('base.view_patient_simple_form').id
        res = super(ThoriumcorpPatient, self)._fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if view_type == 'form':
            res['arch'] = self._fields_view_get_address(res['arch'])
        return res

#    @api.constrains('parent_id')
#    def _check_parent_id(self):
#    @api.constrains('identity_id')
#    def _check_identity_id(self):
#        if not self._check_recursion():
#            raise ValidationError(_('You cannot create recursive Patient hierarchies.'))

    def copy(self, default=None):
        self.ensure_one()
        chosen_name = default.get('name') if default else ''
        new_name = chosen_name or _('%s (copy)') % self.name
        default = dict(default or {}, name=new_name)
        return super(ThoriumcorpPatient, self).copy(default)

#    @api.onchange('parent_id')
#    def onchange_parent_id(self):
#        # return values in result, as this method is used by _fields_sync()
#        if not self.parent_id:
#            return
#        result = {}
#        patient = self._origin
#        if patient.parent_id and patient.parent_id != self.parent_id:
#            result['warning'] = {
#                'title': _('Warning'),
#                'message': _('Changing the company of a contact should only be done if it '
#                             'was never correctly set. If an existing contact starts working for a new '
#                             'company then a new contact should be created under that new '
#                             'company. You can use the "Discard" button to abandon this change.')}
#        if patient.type == 'contact' or self.type == 'contact':
#            # for contacts: copy the parent address, if set (aka, at least one
#            # value is set in the address: otherwise, keep the one from the
#            # contact)
#            address_fields = self._address_fields()
#            if any(self.parent_id[key] for key in address_fields):
#                def convert(value):
#                    return value.id if isinstance(value, models.BaseModel) else value
#                result['value'] = {key: convert(self.parent_id[key]) for key in address_fields}
#        return result

    @api.onchange('country_id')
    def _onchange_country_id(self):
        if self.country_id and self.country_id != self.state_id.country_id:
            self.state_id = False

    @api.onchange('state_id')
    def _onchange_state(self):
        if self.state_id.country_id:
            self.country_id = self.state_id.country_id

#    @api.onchange('email')
#    def onchange_email(self):
#        if not self.image1920 and self._context.get('gravatar_image') and self.email:
#            self.image1920 = self._get_gravatar_image(self.email)

#    @api.onchange('parent_id', 'company_id')
#    def _onchange_company_id(self):
#        if self.parent_id:
#            self.company_id = self.parent_id.company_id.id

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
            patient.company_type = 'company' if patient.is_company else 'person'

    def _write_company_type(self):
        for patient in self:
            patient.is_company = patient.company_type == 'company'

    @api.onchange('company_type')
    def onchange_company_type(self):
        self.is_company = (self.company_type == 'company')

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

#    @api.model
#    def _commercial_fields(self):
#        """ Returns the list of fields that are managed by the commercial entity
#        to which a patient belongs. These fields are meant to be hidden on
#        patients that aren't `commercial entities` themselves, and will be
#        delegated to the parent `commercial entity`. The list is meant to be
#        extended by inheriting classes. """
#        return ['vat', 'credit_limit']
##        return ['credit_limit']

#    def _commercial_sync_from_company(self):
#        """ Handle sync of commercial fields when a new parent commercial entity is set,
#        as if they were related fields """
#        commercial_patient = self.commercial_patient_id
#        if commercial_patient != self:
#            sync_vals = commercial_patient._update_fields_values(self._commercial_fields())
#            self.write(sync_vals)

#    def _commercial_sync_to_children(self):
#        """ Handle sync of commercial fields to descendants """
#        commercial_patient = self.commercial_patient_id
#        sync_vals = commercial_patient._update_fields_values(self._commercial_fields())
#        sync_children = self.child_ids.filtered(lambda c: not c.is_company)
#        for child in sync_children:
#            child._commercial_sync_to_children()
#        res = sync_children.write(sync_vals)
#        sync_children._compute_commercial_patient()
#        return res

    def _fields_sync(self, values):
        """ Sync commercial fields and address fields from company and to children after create/update,
        just as if those were all modeled as fields.related to the parent """
        # 1. From UPSTREAM: sync from parent
#        if values.get('parent_id') or values.get('type') == 'contact':
        if values.get('identity_id') or values.get('type') == 'contact':
            # 1a. Commercial fields: sync if parent changed
#            if values.get('parent_id'):
            if values.get('identity_id'):
                self._commercial_sync_from_company()
            # 1b. Address fields: sync if parent or use_parent changed *and* both are now set
            if self.parent_id and self.type == 'contact':
                onchange_vals = self.onchange_parent_id().get('value', {})
                self.update_address(onchange_vals)

#        # 2. To DOWNSTREAM: sync children
#        self._children_sync(values)

#    def _children_sync(self, values):
#        if not self.child_ids:
#            return
#        # 2a. Commercial Fields: sync if commercial entity
#        if self.commercial_patient_id == self:
#            commercial_fields = self._commercial_fields()
#            if any(field in values for field in commercial_fields):
#                self._commercial_sync_to_children()
#        for child in self.child_ids.filtered(lambda c: not c.is_company):
#            if child.commercial_patient_id != self.commercial_patient_id:
#                self._commercial_sync_to_children()
#                break
#        # 2b. Address fields: sync if address changed
#        address_fields = self._address_fields()
#        if any(field in values for field in address_fields):
#            contacts = self.child_ids.filtered(lambda c: c.type == 'contact')
#            contacts.update_address(values)

#    def _handle_first_contact_creation(self):
#        """ On creation of first contact for a company (or root) that has no address, assume contact address
#        was meant to be company address """
#        parent = self.parent_id
#        address_fields = self._address_fields()
#        if (parent.is_company or not parent.parent_id) and len(parent.child_ids) == 1 and \
#            any(self[f] for f in address_fields) and not any(parent[f] for f in address_fields):
#            addr_vals = self._update_fields_values(address_fields)
#            parent.update_address(addr_vals)

    def _clean_website(self, website):
        url = urls.url_parse(website)
        if not url.scheme:
            if not url.netloc:
                url = url.replace(netloc=url.path, path='')
            website = url.replace(scheme='http').to_url()
        return website

    def write(self, vals):
#        if vals.get('active') is False:
            # DLE: It should not be necessary to modify this to make work the ORM. The problem was just the recompute
            # of patient.user_ids when you create a new user for this patient, see test test_70_archive_internal_patients
            # You modified it in a previous commit, see original commit of this:
            # https://github.com/odoo/odoo/commit/9d7226371730e73c296bcc68eb1f856f82b0b4ed
            #
            # RCO: when creating a user for patient, the user is automatically added in patient.user_ids.
            # This is wrong if the user is not active, as patient.user_ids only returns active users.
            # Hence this temporary hack until the ORM updates inverse fields correctly.
#            self.invalidate_cache(['user_ids'], self._ids)
#            for patient in self:
#                if patient.active and patient.user_ids:
#                    raise ValidationError(_('You cannot archive a contact linked to an internal user.'))
        # thoriumcorp.patient must only allow to set the company_id of a patient if it
        # is the same as the company of all users that inherit from this patient
        # (this is to allow the code from res_users to write to the patient!) or
        # if setting the company_id to False (this is compatible with any user
        # company)
        if vals.get('website'):
            vals['website'] = self._clean_website(vals['website'])
#        if vals.get('parent_id'):
#            vals['company_name'] = False
        if vals.get('company_id'):
            company = self.env['res.company'].browse(vals['company_id'])
#            for patient in self:
#                if patient.user_ids:
#                    companies = set(user.company_id for user in patient.user_ids)
#                    if len(companies) > 1 or company not in companies:
#                        raise UserError(
#                            ("The selected company is not compatible with the companies of the related user(s)"))
#                if patient.child_ids:
#                    patient.child_ids.write({'company_id': company.id})
        result = True
        # To write in SUPERUSER on field is_company and avoid access rights problems.
        if 'is_company' in vals and self.user_has_groups('base.group_patient_manager') and not self.env.su:
            result = super(ThoriumcorpPatient, self.sudo()).write({'is_company': vals.get('is_company')})
            del vals['is_company']
        result = result and super(ThoriumcorpPatient, self).write(vals)
        for patient in self:
#            if any(u.has_group('base.group_user') 
#                for u in patient.user_ids 
#                    if u != self.env.user):
#                        self.env['res.users'].check_access_rights('write') 
            patient._fields_sync(vals)
        return result

    def _load_records_create(self, vals_list):
        patients = super(ThoriumcorpPatient, self.with_context(_patients_skip_fields_sync=True))._load_records_create(vals_list)

        # batch up first part of _fields_sync
        # group patients by commercial_patient_id (if not self) and parent_id (if type == contact)
        groups = collections.defaultdict(list)
        for patient, vals in zip(patients, vals_list):
            cp_id = None
#            if vals.get('parent_id') and patient.commercial_patient_id != patient:
#                cp_id = patient.commercial_patient_id.id

            add_id = None
#            if patient.parent_id and patient.type == 'contact':
#                add_id = patient.parent_id.id
#            groups[(cp_id, add_id)].append(patient.id)
            groups[(add_id)].append(patient.id)

        for (cp_id, add_id), children in groups.items():
            # values from parents (commercial, regular) written to their common children
            to_write = {}
            # commercial fields from commercial patient
            if cp_id:
                to_write = self.browse(cp_id)._update_fields_values(self._commercial_fields())
            # address fields from parent
            if add_id:
                parent = self.browse(add_id)
                for f in self._address_fields():
                    v = parent[f]
                    if v:
                        to_write[f] = v.id if isinstance(v, models.BaseModel) else v
            if to_write:
                self.browse(children).write(to_write)

        # do the second half of _fields_sync the "normal" way
        for patient, vals in zip(patients, vals_list):
#            patient._children_sync(vals)
            patient._handle_first_contact_creation()
        return patients

#    def create_company(self):
#        self.ensure_one()
#        if self.company_name:
#            # Create parent company
#            values = dict(name=self.company_name, is_company=True, vat=self.vat)
#            values.update(self._update_fields_values(self._address_fields()))
#            new_company = self.create(values)
#            # Set new company as my parent
#            self.write({
#                'parent_id': new_company.id, 
#                'child_ids': [(1, identity_id, dict(parent_id=new_company.id)) for identity_id in self.child_ids.ids]
##                'child_ids': [(1, patient_id, dict(parent_id=new_company.id)) for patient_id in self.child_ids.ids]
#            })
#        return True

#    def open_commercial_entity(self):
#        """ Utility method used to add an "Open Company" button in patient views """
#        self.ensure_one()
#        return {'type': 'ir.actions.act_window',
#                'res_model': 'thoriumcorp.patient',
#                'view_mode': 'form',
#                'res_id': self.commercial_patient_id.id,
#                'target': 'current',
#                'flags': {'form': {'action_buttons': True}}}

#    def open_parent(self):
#        """ Utility method used to add an "Open Parent" button in patient views """
#        self.ensure_one()
#        address_form_id = self.env.ref('base.view_patient_address_form').id
#        return {'type': 'ir.actions.act_window',
#                'res_model': 'thoriumcorp.patient',
#                'view_mode': 'form',
#                'views': [(address_form_id, 'form')],
#                'res_id': self.parent_id.id,
#                'target': 'new',
#                'flags': {'form': {'action_buttons': True}}}

#    def _get_contact_name(self, patient, name):
##        return "%s, %s" % (patient.commercial_company_name or patient.sudo().parent_id.name, name)
#        return "%s, %s" % (patient.sudo().parent_id.name, name)

    def _get_name(self):
        """ Utility method to allow name_get to be overrided without re-browse the patient """
        patient = self
        name = patient.name or ''

#        if patient.company_name or patient.parent_id:
        if patient.company_name:
            if not name and patient.type in ['invoice', 'delivery', 'other']:
                name = dict(self.fields_get(['type'])['type']['selection'])[patient.type]
#            if not patient.is_company:
#                name = self._get_contact_name(patient, name)
        if self._context.get('show_address_only'):
            name = patient._display_address(without_company=True)
        if self._context.get('show_address'):
            name = name + "\n" + patient._display_address(without_company=True)
        name = name.replace('\n\n', '\n')
        name = name.replace('\n\n', '\n')
        if self._context.get('address_inline'):
            name = name.replace('\n', ', ')
        if self._context.get('show_email') and patient.email:
            name = "%s <%s>" % (name, patient.email)
        if self._context.get('html_format'):
            name = name.replace('\n', '<br/>')
        if self._context.get('show_vat') and patient.vat:
            name = "%s ‒ %s" % (name, patient.vat)
        return name

    def name_get(self):
        res = []
        for patient in self:
            name = patient._get_name()
            res.append((patient.id, name))
        return res

    def _parse_patient_name(self, text, context=None):
        """ Supported syntax:
            - 'Raoul <raoul@grosbedon.fr>': will find name and email address
            - otherwise: default, everything is set as the name """
        emails = tools.email_split(text.replace(' ', ','))
        if emails:
            email = emails[0]
            name = text[:text.index(email)].replace('"', '').replace('<', '').strip()
        else:
            name, email = text, ''
        return name, email

    @api.model
    def name_create(self, name):
        """ Override of orm's name_create method for patients. The purpose is
            to handle some basic formats to create patients using the
            name_create.
            If only an email address is received and that the regex cannot find
            a name, the name will have the email value.
            If 'force_email' key in context: must find the email address. """
        default_type = self._context.get('default_type')
        if default_type and default_type not in self._fields['type'].get_values(self.env):
            context = dict(self._context)
            context.pop('default_type')
            self = self.with_context(context)
        name, email = self._parse_patient_name(name)
        if self._context.get('force_email') and not email:
            raise UserError(_("Couldn't create contact without email address!"))
        if not name and email:
            name = email
        patient = self.create({self._rec_name: name or email, 'email': email or self.env.context.get('default_email', False)})
        return patient.name_get()[0]

    @api.model
    def _search(self, args, offset=0, limit=None, order=None, count=False, access_rights_uid=None):
        """ Override search() to always show inactive children when searching via ``child_of`` operator. The ORM will
        always call search() with a simple domain of the form [('parent_id', 'in', [ids])]. """
        # a special ``domain`` is set on the ``child_ids`` o2m to bypass this logic, as it uses similar domain expressions
#        if len(args) == 1 and len(args[0]) == 3 \ # and args[0][:2] == ('parent_id','in') \
        if len(args) == 1 and len(args[0]) == 3 and args[0][2] != [False]:
            self = self.with_context(active_test=False)
        return super(ThoriumcorpPatient, self)._search(args, offset=offset, limit=limit, order=order,
                                            count=count, access_rights_uid=access_rights_uid)

#    def _get_name_search_order_by_fields(self):
#        return ''

#    @api.model
#    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
#        self = self.with_user(name_get_uid or self.env.uid)
#        # as the implementation is in SQL, we force the recompute of fields if necessary
##        self.recompute(['display_name'])
#        self.flush()
#        if args is None:
#            args = []
#        order_by_rank = self.env.context.get('thoriumcorp_patient_search_mode') 
#        if (name or order_by_rank) and operator in ('=', 'ilike', '=ilike', 'like', '=like'):
#            self.check_access_rights('write')
##            self.check_access_rights('read')
#            where_query = self._where_calc(args)
#            self._apply_ir_rules(where_query, 'wite')
##            self._apply_ir_rules(where_query, 'read')
#            from_clause, where_clause, where_clause_params = where_query.get_sql()
#            from_str = from_clause if from_clause else 'thoriumcorp_patient'
#            where_str = where_clause and (" WHERE %s AND " % where_clause) or ' WHERE '
#
#            # search on the name of the contacts and of its company
#            search_name = name
#            if operator in ('ilike', 'like'):
#                search_name = '%%%s%%' % name
#            if operator in ('=ilike', '=like'):
#                operator = operator[1:]
#
#            unaccent = get_unaccent_wrapper(self.env.cr)
#
#            fields = self._get_name_search_order_by_fields()
#
#            query = """SELECT thoriumcorp_patient.id
#                         FROM {from_str}
#                      {where} ({email} {operator} {percent}
#                           OR {display_name} {operator} {percent}
#                           OR {reference} {operator} {percent}
#                           OR {vat} {operator} {percent})
#                           -- don't panic, trust postgres bitmap
#                     ORDER BY {fields} {display_name} {operator} {percent} desc,
#                              {display_name}
#                    """.format(from_str=from_str,
#                               fields=fields,
#                               where=where_str,
#                               operator=operator,
#                               email=unaccent('thoriumcorp_patient.email'),
#                               display_name=unaccent('thoriumcorp_patient.display_name'),
#                               reference=unaccent('thoriumcorp_patient.ref'),
#                               percent=unaccent('%s'),
#                               vat=unaccent('thoriumcorp_patient.vat'),)
#
#            where_clause_params += [search_name]*3  # for email / display_name, reference
#            where_clause_params += [re.sub('[^a-zA-Z0-9]+', '', search_name) or None]  # for vat
#            where_clause_params += [search_name]  # for order by
#            if limit:
#                query += ' limit %s'
#                where_clause_params.append(limit)
#            self.env.cr.execute(query, where_clause_params)
#            patient_ids = [row[0] for row in self.env.cr.fetchall()]
#
#            if patient_ids:
#                return models.lazy_name_get(self.browse(patient_ids))
#            else:
#                return []
#        return super(ThoriumcorpPatient, self)._name_search(name, args, operator=operator, limit=limit, name_get_uid=name_get_uid)

    @api.model
    def find_or_create(self, email):
        """ Find a patient with the given ``email`` or use :py:method:`~.name_create`
            to create one

            :param str email: email-like string, which should contain at least one email,
                e.g. ``"Raoul Grosbedon <r.g@grosbedon.fr>"``"""
        assert email, 'an email is required for find_or_create to work'
        emails = tools.email_split(email)
        name_emails = tools.email_split_and_format(email)
        if emails:
            email = emails[0]
            name_email = name_emails[0]
        else:
            name_email = email
        patients = self.search([('email', '=ilike', email)], limit=1)
        return patients.id or self.name_create(name_email)[0]

    def _get_gravatar_image(self, email):
        email_hash = hashlib.md5(email.lower().encode('utf-8')).hexdigest()
        url = "https://www.gravatar.com/avatar/" + email_hash
        try:
            res = requests.get(url, params={'d': '404', 's': '128'}, timeout=5)
            if res.status_code != requests.codes.ok:
                return False
        except requests.exceptions.ConnectionError as e:
            return False
        except requests.exceptions.Timeout as e:
            return False
        return base64.b64encode(res.content)

    def _email_send(self, email_from, subject, body, on_error=None):
        for patient in self.filtered('email'):
            tools.email_send(email_from, [patient.email], subject, body, on_error)
        return True

#    def address_get(self, adr_pref=None):
#        """ Find contacts/addresses of the right type(s) by doing a depth-first-search
#        through descendants within company boundaries (stop at entities flagged ``is_company``)
#        then continuing the search at the ancestors that are within the same company boundaries.
#        Defaults to patients of type ``'default'`` when the exact type is not found, or to the
#        provided patient itself if no type ``'default'`` is found either. """
#        adr_pref = set(adr_pref or [])
#        if 'contact' not in adr_pref:
#            adr_pref.add('contact')
#        result = {}
#        visited = set()
#        for patient in self:
#            current_patient = patient
#            while current_patient:
#                to_scan = [current_patient]
#                # Scan descendants, DFS
#                while to_scan:
#                    record = to_scan.pop(0)
#                    visited.add(record)
#                    if record.type in adr_pref and not result.get(record.type):
#                        result[record.type] = record.id
#                    if len(result) == len(adr_pref):
#                        return result
#                    to_scan = [c for c in record.child_ids
#                                 if c not in visited
#                                 if not c.is_company] + to_scan
#
#                # Continue scanning at ancestor if current_patient is not a commercial entity
#                if current_patient.is_company or not current_patient.parent_id:
#                    break
#                current_patient = current_patient.parent_id

        # default to type 'contact' or the patient itself
        default = result.get('contact', self.id or False)
        for adr_type in adr_pref:
            result[adr_type] = result.get(adr_type) or default
        return result

    @api.model
    def view_header_get(self, view_id, view_type):
        res = super(ThoriumcorpPatient, self).view_header_get(view_id, view_type)
        if res: return res
        if not self._context.get('category_id'):
            return False
        return _('Patients: ') + self.env['thoriumcorp.patient.category'].browse(self._context['category_id']).name

    @api.model
    @api.returns('self')
    def main_patient(self):
        ''' Return the main patient '''
        return self.env.ref('base.main_patient')

    @api.model
    def _get_default_address_format(self):
        return "%(street)s\n%(street2)s\n%(city)s %(state_code)s %(zip)s\n%(country_name)s"

    @api.model
    def _get_address_format(self):
        return self.country_id.address_format or self._get_default_address_format()

    def _display_address(self, without_company=False):

        '''
        The purpose of this function is to build and return an address formatted accordingly to the
        standards of the country where it belongs.

        :param address: browse record of the thoriumcorp.patient to format
        :returns: the address formatted in a display that fit its country habits (or the default ones
            if not country is specified)
        :rtype: string
        '''
        # get the information that will be injected into the display format
        # get the address format
        address_format = self._get_address_format()
        args = {
            'state_code': self.state_id.code or '',
            'state_name': self.state_id.name or '',
            'country_code': self.country_id.code or '',
            'country_name': self._get_country_name(),
#            'company_name': self.commercial_company_name or '',
        }
        for field in self._formatting_address_fields():
            args[field] = getattr(self, field) or ''
        if without_company:
            args['company_name'] = ''
#        elif self.commercial_company_name:
#            address_format = '%(company_name)s\n' + address_format
        address_format = '%(company_name)s\n' + address_format
        return address_format % args

    def _display_address_depends(self):
        # field dependencies of method _display_address()
        return self._formatting_address_fields() + [
            'country_id.address_format', 'country_id.code', 'country_id.name',
            'company_name', 'state_id.code', 'state_id.name',
        ]

    @api.model
    def get_import_templates(self):
        return [{
            'label': _('Import Template for Customers'),
            'template': '/base/static/xls/thoriumcorp.patient.xls'
        }]

    @api.model
    def _check_import_consistency(self, vals_list):
        """
        The values created by an import are generated by a name search, field by field.
        As a result there is no check that the field values are consistent with each others.
        We check that if the state is given a value, it does belong to the given country, or we remove it.
        """
        States = self.env['res.country.state']
        states_ids = {vals['state_id'] for vals in vals_list if vals.get('state_id')}
        state_to_country = States.search([('id', 'in', list(states_ids))]).read(['country_id'])
        for vals in vals_list:
            if vals.get('state_id'):
                country_id = next(c['country_id'][0] for c in state_to_country if c['id'] == vals.get('state_id'))
                state = States.browse(vals['state_id'])
                if state.country_id.id != country_id:
                    state_domain = [('code', '=', state.code),
                                    ('country_id', '=', country_id)]
                    state = States.search(state_domain, limit=1)
                    vals['state_id'] = state.id  # replace state or remove it if not found

    def _get_country_name(self):
        return self.country_id.name or ''


class ResPatientIndustry(models.Model):
    _description = 'Industry'
    _name = "thoriumcorp.patient.industry"
    _order = "name"

    name = fields.Char('Name', translate=True)
    full_name = fields.Char('Full Name', translate=True)
    active = fields.Boolean('Active', default=True)

#+++++++++++++++++++++++++++++++++++++ end of incorporated from res.partner +++++++++++++++++++++++

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
#    patient_id 
    identity_id = fields.Many2one(
        comodel_name='thoriumcorp.patient',
        string='Patient',
        required=True,
        index=True
    )
    test_type = fields.Many2one(
        comodel_name='thoriumcorp.lab.test.type',
        string='Test Type',
        required=True,
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
                'default_patient': self.identity_id.id,
#                'default_patient': self.patient_id.id, identity_id
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
#        readonly=True,
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

class ThoriumcorpPractitioner(models.Model):
    _name = 'thoriumcorp.practitioner'
    _description = 'Thoriumcorp Practitioner'
#    _inherit = 'thoriumcorp.abstract_entity'
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
        string='Code',
        help='Speciality code',
        size=256,
        required=True,
    )
    name = fields.Char(
        string='Name',
        help='Name of the specialty',
        size=256,
        required=True,
    )
    category = fields.Selection(
        [
            ('clinical', 'Clinical specialties'),
            ('surgical', 'Surgical specialties'),
            ('medical', 'Medical-surgical specialties'),
            ('diagnostic', 'Laboratory or diagnostic specialties'),
        ],
        'Category of specialty'
    )



#class ThoriumcorpPatientDisease(models.Model):
#    _name = 'thoriumcorp.patient_disease'
#    _inherit = 'thoriumcorp.patient_disease'
#
#    practitioner_id = fields.Many2one(
#        comodel_name='thoriumcorp.practitioner',
#        string='Physician', index=True
#    )

class MedicalCenter(models.Model):
    _name = 'medical.center'
    _description = 'Medical Center'
    _sql_constraints = [('code_uniq', 'unique(code)', 'This code exists')]

    code = fields.Char(
        'Code',
        required=True
    )
    institution_type = fields.Selection(
        [
            ('doctor_office', 'Doctor office'),
            ('primary_care', 'Primary care center'),
            ('clinic', 'Clinic'),
            ('hospital', 'General Hospital'),
            ('specialized', 'Specialized Hospital'),
            ('nursing_home', 'Nursing home'),
            ('hospice', 'Hospice'),
            ('rural', 'Rural instalation'),
            ('pasi', 'PASI'),
            ('cat', 'CAT'),
            ('cdi', 'CDI'),
        ],
        'Type',
        required=True,
        sort=False
    )
    beds = fields.Integer("Beds")
    operating_room = fields.Boolean(
        "Operating room",
        help="Does the institution have an operating room?",
    )
    or_number = fields.Integer("Operating rooms")
    public_level = fields.Selection(
        [
            ('private', 'Private'),
            ('public', 'Public'),
            ('mixed', 'Mixed'),
        ],
        'Public level',
        required=True,
        sort=False
    )
    teaching = fields.Boolean(
        "Teaching",
        help="Is it a teaching institution?"
    )
    heliport = fields.Boolean("Heliport")
    trauma_center = fields.Boolean("Trauma center")
    trauma_level = fields.Selection(
        [
            ('I', 'Level I'),
            ('II', 'Level II'),
            ('III', 'Level III'),
            ('IV', 'Level IV'),
            ('V', 'Level V'),
        ],
        'Trauma level',
        sort=False
    )
    extra_info = fields.Text("Additional information")
    specialties = fields.One2many(
        'institution.specialties',
        'name',
        'Specialties',
        help="Specialties Provided in this Medical Institution"
    )
    main_specialty = fields.Many2one(
        'institution.specialties',
        'Specialty',
        help="Main specialty, for specialized hospitals",
    )
    operational_sectors = fields.One2many(
        'institution.operationalsector',
        'name',
        'Operational Sector',
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


# Ported from GnuHealth
# class OperationalSector(models.Model):
#     _name = 'operational.sector'
#     _description = 'Operational Sector'
#
#     name = fields.Char(
#         'Op. Sector', required=True,
#         help='Region included in an operational area')
#     operational_area = fields.Many2one(
#         'operational.area', 'Operational Area')
#     info = fields.Text('Extra Information')
#
#     _sql_constraints = [
#         (
#             'operational_area_name_uniq',
#             'unique(name, operational_area)',
#             'The operational sector must be unique in each operational area!'
#         )
#     ]


class MedicalInstitutionSpecialties(models.Model):
    _name = 'institution.specialties'
    _description = 'Medical Institution Specialties'

    name = fields.Many2one(
        'medical.center',
        'Institution',
        required=True
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
    _description = 'Operational Sectors covered by this institution'

    name = fields.Many2one(
        'medical.center',
        'Institution',
        required=True
    )
    # operational_sector = fields.Many2one(
    #     'operational.sector',
    #     'Operational Sector',
    #     required=True
    # )


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
        'Institution',
        required=True,
        help='Medical Institution of this building'
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
    _description = 'Hospital Unit'

    name = fields.Char(
        'Name',
        required=True,
        help='Name of the unit, eg. Neonatal, Intensive Care ...'
    )
    institution = fields.Many2one(
        'medical.center',
        'Institution',
        required=True,
        help='Medical Institution'
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
    _description = 'Operating Room'

    name = fields.Char(
        'Name',
        required=True,
        help='Operating room name'
    )
    institution = fields.Many2one(
        'medical.center',
        'Institution',
        required=True,
        help='Medical Institution'
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
        'Institution',
        required=True
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


#class ProductTemplate(models.Model):
#    _inherit = "product.template"
#
#    is_bed = fields.Boolean('Bed', help='Check if the product is a bed')
#

class HospitalBed(models.Model):
    _name = 'hospital.bed'
    _rec_name = 'telephone_number'
    _description = 'Hospital Bed'

    name = fields.Many2one(
        'product.product',
        'Bed',
        required=True,
#        domain=[('is_bed', '=', True)],
        help='Bed Number'
    )
    institution = fields.Many2one(
        'medical.center',
        'Institution',
        required=True,
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

    # Redefine active so that it is managed independently from partner.
#    active = fields.Boolean(
#        default=True,
#    )
#    partner_id = fields.Many2one(
#        string='Related Partner',
#        comodel_name='res.partner',
#        required=True,
#        ondelete='cascade',
#        index=True,
#    )

    @api.model
    @api.returns('self', lambda value: value.id)
    def create(self, vals):
        vals = self._create_vals(vals)
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
#                    ('parent_id', 'child_of', record.partner_id.id),
                    ('active', '=', True),
                ])
                if not entities:
                    record.partner_id.active = False

#    @api.model
#    def _create_vals(self, vals):
#        """ Override this in child classes in order to add default values. """
#        if self._allow_image_create(vals):
#            vals['image'] = self._get_default_image_encoded(vals)
#        return vals

#    def _allow_image_create(self, vals):
#        """ It determines if conditions are present that should stop image gen.
#
#        This is implemented so that tests aren't wildly creating images left
#         and right for no reason. Child classes could also inherit this to
#         provide custom rules for image generation.
#
#        Note that this method explicitly allows image generation if
#         ``__image_create_allow`` is a ``True`` value in the context. Any
#         child that chooses to provide custom rules shall also adhere to this
#         context, unless there is a documented reason to not do so.
#        """
#        return False
#        if vals.get('image'):
#            return False
#        if any((
#            getattr(threading.currentThread(), 'testing', False),
#            self._context.get('install_mode')
#        )):
#            if not self.env.context.get('__image_create_allow'):
#                return False
#        return True

    def toggle(self, attr):
        if getattr(self, attr) is True:
            self.write({attr: False})
        elif getattr(self, attr) is False:
            self.write({attr: True})


