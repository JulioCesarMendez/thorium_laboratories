#
#    Copyright (C) 2020-2030 Thorium Corp FP <help@thoriumcorp.website>
#

import threading
from odoo import api, fields, models


class ThoriumcorpAbstractEntity(models.AbstractModel):
    _name = 'thoriumcorp.abstract_entity'
    _description = 'Thorium Corp FP Abstract Entity'
    _inherits = {'res.patient': 'partner_id'}
#    _inherits = {'thoriumcorp.partner': 'partner_id'}
#    _inherits = {'res.partner': 'partner_id'}
#    _inherits = {'thoriumcorp.partner': 'partner_id'}
#    _inherit = ['mail.thread']

    # Redefine active so that it is managed independently from partner.
#    active = fields.Boolean(
#        default=True,
#    )
#    partner_id = fields.Many2one(
#        string='Related Partner',
#        comodel_name='thoriumcorp.partner',
##        comodel_name='res.partner',
#        required=True,
#        ondelete='cascade',
#        index=True,
#    )

    @api.model
    @api.returns('self', lambda value: value.id)
    def create(self, vals):
        vals = self._create_vals(vals)
        return super(ThoriumcorpAbstractEntity, self).create(vals)

    def toggle_active(self):
        """ It toggles patient and partner activation. """
        for record in self:
            super(ThoriumcorpAbstractEntity, self).toggle_active()
            if record.active:
                record.partner_id.active = True
            else:
                entities = record.env[record._name].search([
                    ('partner_id', 'child_of', record.partner_id.id),
                    ('parent_id', 'child_of', record.partner_id.id),
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

