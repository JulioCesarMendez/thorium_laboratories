# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.

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

from odoo import api, fields, models, tools, SUPERUSER_ID, _
from odoo.modules import get_module_resource
from odoo.osv.expression import get_unaccent_wrapper
from odoo.exceptions import UserError, ValidationError

# Global variables used for the warning fields declared on the res.patient
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


class FormatAddressMixin(models.AbstractModel):
    _name = "format.address.mixin"
    _description = 'Address Format'

    def _fields_view_get_address(self, arch):
        # consider the country of the user, not the country of the patient we want to display
        address_view_id = self.env.company.country_id.address_view_id
        if address_view_id and not self._context.get('no_address_format'):
            #render the patient address accordingly to address_view_id
            doc = etree.fromstring(arch)
            for address_node in doc.xpath("//div[hasclass('o_address_format')]"):
                Patient = self.env['res.patient'].with_context(no_address_format=True)
                sub_view = Patient.fields_view_get(
                    view_id=address_view_id.id, view_type='form', toolbar=False, submenu=False)
                sub_view_node = etree.fromstring(sub_view['arch'])
                #if the model is different than res.patient, there are chances that the view won't work
                #(e.g fields not present on the model). In that case we just return arch
                if self._name != 'res.patient':
                    try:
                        self.env['ir.ui.view'].postprocess_and_fields(self._name, sub_view_node, None)
                    except ValueError:
                        return arch
                address_node.getparent().replace(address_node, sub_view_node)
            arch = etree.tostring(doc, encoding='unicode')
        return arch

class PatientCategory(models.Model):
    _description = 'Patient Tags'
    _name = 'res.patient.category'
    _order = 'name'
    _parent_store = True

#    name = fields.Char(string='Tag Name', required=True, translate=True)
    color = fields.Integer(string='Color Index')
    parent_id = fields.Many2one('res.patient.category', string='Parent Category', index=True, ondelete='cascade')
    child_ids = fields.One2many('res.patient.category', 'parent_id', string='Child Tags')
    active = fields.Boolean(default=True, help="The active field allows you to hide the category without removing it.")
    parent_path = fields.Char(index=True)
    patient_ids = fields.Many2many('res.patient', column1='category_id', column2='patient_id', string='Patients')

    @api.constrains('parent_id')
    def _check_parent_id(self):
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
            return super(PatientCategory, self).name_get()

        res = []
        for category in self:
            names = []
            current = category
            while current:
                names.append(current.name)
                current = current.parent_id
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
    _name = 'res.patient.title'
    _order = 'name'
    _description = 'Patient Title'

#    name = fields.Char(string='Title', required=True, translate=True)
    shortcut = fields.Char(string='Abbreviation', translate=True)


class Patient(models.Model):
    _description = 'Patients'
#    _inherit = ['format.address.mixin', 'image.mixin']
    _inherit = ['format.address.mixin']
    _name = "res.patient"
    _order = "display_name"

    def _default_category(self):
        return self.env['res.patient.category'].browse(self._context.get('category_id'))

    @api.model
    def default_get(self, default_fields):
        """Add the company of the parent as default if we are creating a child patient."""
        values = super().default_get(default_fields)
        if 'parent_id' in default_fields and values.get('parent_id'):
            values['company_id'] = self.browse(values.get('parent_id')).company_id.id
        return values

    def _split_street_with_params(self, street_raw, street_format):
        return {'street': street_raw}

#    name = fields.Char(index=True)
    display_name = fields.Char(compute='_compute_display_name', store=True, index=True)
    date = fields.Date(index=True)
    title = fields.Many2one('res.patient.title')
    parent_id = fields.Many2one('res.patient', string='Related Company', index=True)
    parent_name = fields.Char(related='parent_id.name', readonly=True, string='Parent name')
    child_ids = fields.One2many('res.patient', 'parent_id', string='Contact', domain=[('active', '=', True)])  # force "active_test" domain to bypass _search() override
    ref = fields.Char(string='Reference', index=True)
    lang = fields.Selection(_lang_get, string='Language', default=lambda self: self.env.lang,
                            help="All the emails and documents sent to this contact will be translated in this language.")
    active_lang_count = fields.Integer(compute='_compute_active_lang_count')
    tz = fields.Selection(_tz_get, string='Timezone', default=lambda self: self._context.get('tz'),
                          help="When printing documents and exporting/importing data, time values are computed according to this timezone.\n"
                               "If the timezone is not set, UTC (Coordinated Universal Time) is used.\n"
                               "Anywhere else, time values are computed according to the time offset of your web client.")

    tz_offset = fields.Char(compute='_compute_tz_offset', string='Timezone offset', invisible=True)
    user_id = fields.Many2one('res.users', string='Salesperson',
      help='The internal user in charge of this contact.')
    vat = fields.Char(string='Tax ID', help="The Tax Identification Number. Complete it if the contact is subjected to government taxes. Used in some legal statements.")
    same_vat_patient_id = fields.Many2one('res.patient', string='Patient with same Tax ID', compute='_compute_same_vat_patient_id', store=False)
    bank_ids = fields.One2many('res.partner.bank', 'partner_id', string='Banks')
    website = fields.Char('Website Link')
    comment = fields.Text(string='Notes')

    category_id = fields.Many2many('res.patient.category', column1='patient_id',
                                    column2='category_id', string='Tags', default=_default_category)
    credit_limit = fields.Float(string='Credit Limit')
    active = fields.Boolean(default=True)
    employee = fields.Boolean(help="Check this box if this contact is an Employee.")
    function = fields.Char(string='Job Position')
    type = fields.Selection(
        [('contact', 'Contact'),
         ('invoice', 'Invoice Address'),
         ('delivery', 'Delivery Address'),
         ('other', 'Other Address'),
         ("private", "Private Address"),
        ], string='Address Type',
        default='contact',
        help="Invoice & Delivery addresses are used in sales orders. Private addresses are only visible by authorized users.")
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
    industry_id = fields.Many2one('res.patient.industry', 'Industry')
    # company_type is only an interface field, do not use it in business logic
    company_type = fields.Selection(string='Company Type',
        selection=[('person', 'Individual'), ('company', 'Company')],
        compute='_compute_company_type', inverse='_write_company_type')
    company_id = fields.Many2one('res.company', 'Company', index=True)
    color = fields.Integer(string='Color Index', default=0)
    user_ids = fields.One2many('res.users', 'partner_id', string='Users', auto_join=True)
    patient_share = fields.Boolean(
        'Share Patient', compute='_compute_patient_share', store=True,
        help="Either customer (not a user), either shared user. Indicated the current patient is a customer without "
             "access or with a limited access created for sharing data.")
    contact_address = fields.Char(compute='_compute_contact_address', string='Complete Address')

    # technical field used for managing commercial fields
    partner_id = fields.Many2one(string='Related Partner', comodel_name='res.patient', required=True, 
                                             ondelete='cascade', store=True, index=True)
    commercial_patient_id = fields.Many2one('res.patient', compute='_compute_commercial_patient',
                                             string='Commercial Entity', store=True, index=True)
    commercial_company_name = fields.Char('Company Name Entity', compute='_compute_commercial_company_name',
                                          store=True)
    company_name = fields.Char('Company Name')

    # fields for medical use
# ****************************************************************************************

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

    # all image fields are base64 encoded and PIL-supported

#    image1920 = fields.Image("Image", max_width=1920, max_height=1920)

    # resized fields stored (as attachment) for performance
#    image_1024 = fields.Image("Image 1024", related="image1920", max_width=1024, max_height=1024, store=True)
#    image_512 = fields.Image("Image 512", related="image1920", max_width=512, max_height=512, store=True)
#    image_256 = fields.Image("Image 256", related="image1920", max_width=256, max_height=256, store=True)
#    image_128 = fields.Image("Image 128", related="image1920", max_width=128, max_height=128, store=True)

    # hack to allow using plain browse record in qweb views, and used in ir.qweb.field.contact
    self = fields.Many2one(comodel_name=_name, compute='_compute_get_ids')

    _sql_constraints = [
        ('check_name', "CHECK( (type='contact' AND name IS NOT NULL) or (type!='contact') )", 'Contacts require a name'),
    ]

    def init(self):
        self._cr.execute("""SELECT indexname FROM pg_indexes WHERE indexname = 'res_patient_vat_index'""")
        if not self._cr.fetchone():
            self._cr.execute("""CREATE INDEX res_patient_vat_index ON res_patient (regexp_replace(upper(vat), '[^A-Z0-9]+', '', 'g'))""")

    @api.depends('is_company', 'name', 'parent_id.display_name', 'type', 'company_name')
    def _compute_display_name(self):
        diff = dict(show_address=None, show_address_only=None, show_email=None, html_format=None, show_vat=None)
        names = dict(self.with_context(**diff).name_get())
        for patient in self:
            patient.display_name = names.get(patient.id)

    @api.depends('lang')
    def _compute_active_lang_count(self):
        lang_count = len(self.env['res.lang'].get_installed())
        for patient in self:
            patient.active_lang_count = lang_count

    @api.depends('tz')
    def _compute_tz_offset(self):
        for patient in self:
            patient.tz_offset = datetime.datetime.now(pytz.timezone(patient.tz or 'GMT')).strftime('%z')

    @api.depends('user_ids.share', 'user_ids.active')
    def _compute_patient_share(self):
        super_patient = self.env['res.users'].browse(SUPERUSER_ID).patient_id
        if super_patient in self:
            super_patient.patient_share = False
        for patient in self - super_patient:
            patient.patient_share = not patient.user_ids or not any(not user.share for user in patient.user_ids)

    @api.depends('vat')
    def _compute_same_vat_patient_id(self):
        for patient in self:
            # use _origin to deal with onchange()
            patient_id = patient._origin.id
            domain = [('vat', '=', patient.vat)]
            if patient_id:
                domain += [('id', '!=', patient_id), '!', ('id', 'child_of', patient_id)]
            patient.same_vat_patient_id = bool(patient.vat) and not patient.parent_id and self.env['res.patient'].search(domain, limit=1)

    @api.depends(lambda self: self._display_address_depends())
    def _compute_contact_address(self):
        for patient in self:
            patient.contact_address = patient._display_address()

    def _compute_get_ids(self):
        for patient in self:
            patient.self = patient.id

    @api.depends('is_company', 'parent_id.commercial_patient_id')
    def _compute_commercial_patient(self):
        for patient in self:
            if patient.is_company or not patient.parent_id:
                patient.commercial_patient_id = patient
            else:
                patient.commercial_patient_id = patient.parent_id.commercial_patient_id

    @api.depends('company_name', 'parent_id.is_company', 'commercial_patient_id.name')
    def _compute_commercial_company_name(self):
        for patient in self:
            p = patient.commercial_patient_id
            patient.commercial_company_name = p.is_company and p.name or patient.company_name

    @api.model
    def _fields_view_get(self, view_id=None, view_type='form', toolbar=False, submenu=False):
        if (not view_id) and (view_type == 'form') and self._context.get('force_email'):
            view_id = self.env.ref('base.view_patient_simple_form').id
        res = super(Patient, self)._fields_view_get(view_id=view_id, view_type=view_type, toolbar=toolbar, submenu=submenu)
        if view_type == 'form':
            res['arch'] = self._fields_view_get_address(res['arch'])
        return res

    @api.constrains('parent_id')
    def _check_parent_id(self):
        if not self._check_recursion():
            raise ValidationError(_('You cannot create recursive Patient hierarchies.'))

    def copy(self, default=None):
        self.ensure_one()
        chosen_name = default.get('name') if default else ''
        new_name = chosen_name or _('%s (copy)') % self.name
        default = dict(default or {}, name=new_name)
        return super(Patient, self).copy(default)

    @api.onchange('parent_id')
    def onchange_parent_id(self):
        # return values in result, as this method is used by _fields_sync()
        if not self.parent_id:
            return
        result = {}
        patient = self._origin
        if patient.parent_id and patient.parent_id != self.parent_id:
            result['warning'] = {
                'title': _('Warning'),
                'message': _('Changing the company of a contact should only be done if it '
                             'was never correctly set. If an existing contact starts working for a new '
                             'company then a new contact should be created under that new '
                             'company. You can use the "Discard" button to abandon this change.')}
        if patient.type == 'contact' or self.type == 'contact':
            # for contacts: copy the parent address, if set (aka, at least one
            # value is set in the address: otherwise, keep the one from the
            # contact)
            address_fields = self._address_fields()
            if any(self.parent_id[key] for key in address_fields):
                def convert(value):
                    return value.id if isinstance(value, models.BaseModel) else value
                result['value'] = {key: convert(self.parent_id[key]) for key in address_fields}
        return result

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

    @api.onchange('parent_id', 'company_id')
    def _onchange_company_id(self):
        if self.parent_id:
            self.company_id = self.parent_id.company_id.id

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
            return super(Patient, self).write(addr_vals)

    @api.model
    def _commercial_fields(self):
        """ Returns the list of fields that are managed by the commercial entity
        to which a patient belongs. These fields are meant to be hidden on
        patients that aren't `commercial entities` themselves, and will be
        delegated to the parent `commercial entity`. The list is meant to be
        extended by inheriting classes. """
        return ['vat', 'credit_limit']

    def _commercial_sync_from_company(self):
        """ Handle sync of commercial fields when a new parent commercial entity is set,
        as if they were related fields """
        commercial_patient = self.commercial_patient_id
        if commercial_patient != self:
            sync_vals = commercial_patient._update_fields_values(self._commercial_fields())
            self.write(sync_vals)

    def _commercial_sync_to_children(self):
        """ Handle sync of commercial fields to descendants """
        commercial_patient = self.commercial_patient_id
        sync_vals = commercial_patient._update_fields_values(self._commercial_fields())
        sync_children = self.child_ids.filtered(lambda c: not c.is_company)
        for child in sync_children:
            child._commercial_sync_to_children()
        res = sync_children.write(sync_vals)
        sync_children._compute_commercial_patient()
        return res

    def _fields_sync(self, values):
        """ Sync commercial fields and address fields from company and to children after create/update,
        just as if those were all modeled as fields.related to the parent """
        # 1. From UPSTREAM: sync from parent
        if values.get('parent_id') or values.get('type') == 'contact':
            # 1a. Commercial fields: sync if parent changed
            if values.get('parent_id'):
                self._commercial_sync_from_company()
            # 1b. Address fields: sync if parent or use_parent changed *and* both are now set
            if self.parent_id and self.type == 'contact':
                onchange_vals = self.onchange_parent_id().get('value', {})
                self.update_address(onchange_vals)

        # 2. To DOWNSTREAM: sync children
        self._children_sync(values)

    def _children_sync(self, values):
        if not self.child_ids:
            return
        # 2a. Commercial Fields: sync if commercial entity
        if self.commercial_patient_id == self:
            commercial_fields = self._commercial_fields()
            if any(field in values for field in commercial_fields):
                self._commercial_sync_to_children()
        for child in self.child_ids.filtered(lambda c: not c.is_company):
            if child.commercial_patient_id != self.commercial_patient_id:
                self._commercial_sync_to_children()
                break
        # 2b. Address fields: sync if address changed
        address_fields = self._address_fields()
        if any(field in values for field in address_fields):
            contacts = self.child_ids.filtered(lambda c: c.type == 'contact')
            contacts.update_address(values)

    def _handle_first_contact_creation(self):
        """ On creation of first contact for a company (or root) that has no address, assume contact address
        was meant to be company address """
        parent = self.parent_id
        address_fields = self._address_fields()
        if (parent.is_company or not parent.parent_id) and len(parent.child_ids) == 1 and \
            any(self[f] for f in address_fields) and not any(parent[f] for f in address_fields):
            addr_vals = self._update_fields_values(address_fields)
            parent.update_address(addr_vals)

    def _clean_website(self, website):
        url = urls.url_parse(website)
        if not url.scheme:
            if not url.netloc:
                url = url.replace(netloc=url.path, path='')
            website = url.replace(scheme='http').to_url()
        return website

    def write(self, vals):
        if vals.get('active') is False:
            # DLE: It should not be necessary to modify this to make work the ORM. The problem was just the recompute
            # of patient.user_ids when you create a new user for this patient, see test test_70_archive_internal_patients
            # You modified it in a previous commit, see original commit of this:
            # https://github.com/odoo/odoo/commit/9d7226371730e73c296bcc68eb1f856f82b0b4ed
            #
            # RCO: when creating a user for patient, the user is automatically added in patient.user_ids.
            # This is wrong if the user is not active, as patient.user_ids only returns active users.
            # Hence this temporary hack until the ORM updates inverse fields correctly.
            self.invalidate_cache(['user_ids'], self._ids)
            for patient in self:
                if patient.active and patient.user_ids:
                    raise ValidationError(_('You cannot archive a contact linked to an internal user.'))
        # res.patient must only allow to set the company_id of a patient if it
        # is the same as the company of all users that inherit from this patient
        # (this is to allow the code from res_users to write to the patient!) or
        # if setting the company_id to False (this is compatible with any user
        # company)
        if vals.get('website'):
            vals['website'] = self._clean_website(vals['website'])
        if vals.get('parent_id'):
            vals['company_name'] = False
        if vals.get('company_id'):
            company = self.env['res.company'].browse(vals['company_id'])
            for patient in self:
                if patient.user_ids:
                    companies = set(user.company_id for user in patient.user_ids)
                    if len(companies) > 1 or company not in companies:
                        raise UserError(
                            ("The selected company is not compatible with the companies of the related user(s)"))
                if patient.child_ids:
                    patient.child_ids.write({'company_id': company.id})
        result = True
        # To write in SUPERUSER on field is_company and avoid access rights problems.
        if 'is_company' in vals and self.user_has_groups('base.group_patient_manager') and not self.env.su:
            result = super(Patient, self.sudo()).write({'is_company': vals.get('is_company')})
            del vals['is_company']
        result = result and super(Patient, self).write(vals)
        for patient in self:
            if any(u.has_group('base.group_user') for u in patient.user_ids if u != self.env.user):
                self.env['res.users'].check_access_rights('write')
            patient._fields_sync(vals)
        return result

    @api.model_create_multi
    def create(self, vals_list):
        if self.env.context.get('import_file'):
            self._check_import_consistency(vals_list)
        for vals in vals_list:
            if vals.get('website'):
                vals['website'] = self._clean_website(vals['website'])
            if vals.get('parent_id'):
                vals['company_name'] = False
        patients = super(Patient, self).create(vals_list)

        if self.env.context.get('_patients_skip_fields_sync'):
            return patients

        for patient, vals in zip(patients, vals_list):
            patient._fields_sync(vals)
            patient._handle_first_contact_creation()
        return patients

    def _load_records_create(self, vals_list):
        patients = super(Patient, self.with_context(_patients_skip_fields_sync=True))._load_records_create(vals_list)

        # batch up first part of _fields_sync
        # group patients by commercial_patient_id (if not self) and parent_id (if type == contact)
        groups = collections.defaultdict(list)
        for patient, vals in zip(patients, vals_list):
            cp_id = None
            if vals.get('parent_id') and patient.commercial_patient_id != patient:
                cp_id = patient.commercial_patient_id.id

            add_id = None
            if patient.parent_id and patient.type == 'contact':
                add_id = patient.parent_id.id
            groups[(cp_id, add_id)].append(patient.id)

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
            patient._children_sync(vals)
            patient._handle_first_contact_creation()
        return patients

    def create_company(self):
        self.ensure_one()
        if self.company_name:
            # Create parent company
            values = dict(name=self.company_name, is_company=True, vat=self.vat)
            values.update(self._update_fields_values(self._address_fields()))
            new_company = self.create(values)
            # Set new company as my parent
            self.write({
                'parent_id': new_company.id,
                'child_ids': [(1, patient_id, dict(parent_id=new_company.id)) for patient_id in self.child_ids.ids]
            })
        return True

    def open_commercial_entity(self):
        """ Utility method used to add an "Open Company" button in patient views """
        self.ensure_one()
        return {'type': 'ir.actions.act_window',
                'res_model': 'res.patient',
                'view_mode': 'form',
                'res_id': self.commercial_patient_id.id,
                'target': 'current',
                'flags': {'form': {'action_buttons': True}}}

    def open_parent(self):
        """ Utility method used to add an "Open Parent" button in patient views """
        self.ensure_one()
        address_form_id = self.env.ref('base.view_patient_address_form').id
        return {'type': 'ir.actions.act_window',
                'res_model': 'res.patient',
                'view_mode': 'form',
                'views': [(address_form_id, 'form')],
                'res_id': self.parent_id.id,
                'target': 'new',
                'flags': {'form': {'action_buttons': True}}}

    def _get_contact_name(self, patient, name):
        return "%s, %s" % (patient.commercial_company_name or patient.sudo().parent_id.name, name)

    def _get_name(self):
        """ Utility method to allow name_get to be overrided without re-browse the patient """
        patient = self
        name = patient.name or ''

        if patient.company_name or patient.parent_id:
            if not name and patient.type in ['invoice', 'delivery', 'other']:
                name = dict(self.fields_get(['type'])['type']['selection'])[patient.type]
            if not patient.is_company:
                name = self._get_contact_name(patient, name)
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
        if len(args) == 1 and len(args[0]) == 3 and args[0][:2] == ('parent_id','in') \
                and args[0][2] != [False]:
            self = self.with_context(active_test=False)
        return super(Patient, self)._search(args, offset=offset, limit=limit, order=order,
                                            count=count, access_rights_uid=access_rights_uid)

    def _get_name_search_order_by_fields(self):
        return ''

    @api.model
    def _name_search(self, name, args=None, operator='ilike', limit=100, name_get_uid=None):
        self = self.with_user(name_get_uid or self.env.uid)
        # as the implementation is in SQL, we force the recompute of fields if necessary
        self.recompute(['display_name'])
        self.flush()
        if args is None:
            args = []
        order_by_rank = self.env.context.get('res_patient_search_mode') 
        if (name or order_by_rank) and operator in ('=', 'ilike', '=ilike', 'like', '=like'):
            self.check_access_rights('read')
            where_query = self._where_calc(args)
            self._apply_ir_rules(where_query, 'read')
            from_clause, where_clause, where_clause_params = where_query.get_sql()
            from_str = from_clause if from_clause else 'res_patient'
            where_str = where_clause and (" WHERE %s AND " % where_clause) or ' WHERE '

            # search on the name of the contacts and of its company
            search_name = name
            if operator in ('ilike', 'like'):
                search_name = '%%%s%%' % name
            if operator in ('=ilike', '=like'):
                operator = operator[1:]

            unaccent = get_unaccent_wrapper(self.env.cr)

            fields = self._get_name_search_order_by_fields()

            query = """SELECT res_patient.id
                         FROM {from_str}
                      {where} ({email} {operator} {percent}
                           OR {display_name} {operator} {percent}
                           OR {reference} {operator} {percent}
                           OR {vat} {operator} {percent})
                           -- don't panic, trust postgres bitmap
                     ORDER BY {fields} {display_name} {operator} {percent} desc,
                              {display_name}
                    """.format(from_str=from_str,
                               fields=fields,
                               where=where_str,
                               operator=operator,
                               email=unaccent('res_patient.email'),
                               display_name=unaccent('res_patient.display_name'),
                               reference=unaccent('res_patient.ref'),
                               percent=unaccent('%s'),
                               vat=unaccent('res_patient.vat'),)

            where_clause_params += [search_name]*3  # for email / display_name, reference
            where_clause_params += [re.sub('[^a-zA-Z0-9]+', '', search_name) or None]  # for vat
            where_clause_params += [search_name]  # for order by
            if limit:
                query += ' limit %s'
                where_clause_params.append(limit)
            self.env.cr.execute(query, where_clause_params)
            patient_ids = [row[0] for row in self.env.cr.fetchall()]

            if patient_ids:
                return models.lazy_name_get(self.browse(patient_ids))
            else:
                return []
        return super(Patient, self)._name_search(name, args, operator=operator, limit=limit, name_get_uid=name_get_uid)

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

    def address_get(self, adr_pref=None):
        """ Find contacts/addresses of the right type(s) by doing a depth-first-search
        through descendants within company boundaries (stop at entities flagged ``is_company``)
        then continuing the search at the ancestors that are within the same company boundaries.
        Defaults to patients of type ``'default'`` when the exact type is not found, or to the
        provided patient itself if no type ``'default'`` is found either. """
        adr_pref = set(adr_pref or [])
        if 'contact' not in adr_pref:
            adr_pref.add('contact')
        result = {}
        visited = set()
        for patient in self:
            current_patient = patient
            while current_patient:
                to_scan = [current_patient]
                # Scan descendants, DFS
                while to_scan:
                    record = to_scan.pop(0)
                    visited.add(record)
                    if record.type in adr_pref and not result.get(record.type):
                        result[record.type] = record.id
                    if len(result) == len(adr_pref):
                        return result
                    to_scan = [c for c in record.child_ids
                                 if c not in visited
                                 if not c.is_company] + to_scan

                # Continue scanning at ancestor if current_patient is not a commercial entity
                if current_patient.is_company or not current_patient.parent_id:
                    break
                current_patient = current_patient.parent_id

        # default to type 'contact' or the patient itself
        default = result.get('contact', self.id or False)
        for adr_type in adr_pref:
            result[adr_type] = result.get(adr_type) or default
        return result

    @api.model
    def view_header_get(self, view_id, view_type):
        res = super(Patient, self).view_header_get(view_id, view_type)
        if res: return res
        if not self._context.get('category_id'):
            return False
        return _('Patients: ') + self.env['res.patient.category'].browse(self._context['category_id']).name

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

        :param address: browse record of the res.patient to format
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
            'company_name': self.commercial_company_name or '',
        }
        for field in self._formatting_address_fields():
            args[field] = getattr(self, field) or ''
        if without_company:
            args['company_name'] = ''
        elif self.commercial_company_name:
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
            'template': '/base/static/xls/res_patient.xls'
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
    _name = "res.patient.industry"
    _order = "name"

#    name = fields.Char('Name', translate=True)
    full_name = fields.Char('Full Name', translate=True)
    active = fields.Boolean('Active', default=True)


