#
#    Copyright (C) 2020-2030 Thorium Corp FP <help@thoriumcorp.website>
#

from odoo import models, fields


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
            ('thoriumcorp', 'Medical-surgical specialties'),
            ('diagnostic', 'Laboratory or diagnostic specialties'),
        ],
        'Category of specialty'
    )
    # This is referenced in
    # https://es.wikipedia.org/wiki/Especialidades_médicas#Especialidades_clínicas
