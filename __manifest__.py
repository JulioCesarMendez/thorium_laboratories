#
#    Copyright (C) 2020-2030 Thorium Corp FP <help@thoriumcorp.website>
#

{
    'name': "Thorium Corp Laboratories",
    'summary': """
        Thorium Corp Laboratories Module
    """,
    'description': """
        Thorium Corp Laboratories Module 
        for remote Clinic Laboratories Management
        ################################

        This modules includes lab tests:

            * Values
            * Reports
            * PoS
            * Medical-derived modules
    """,
    'author': "Thorium Corp FP",
    'website': "https://thoriumcorp.website",
    'category': 'Thoriumcorp',
    'version': '12.0.0.0.1',
    'depends': ['base', 'mail', 'product', 'contacts'],
    'data': [
        'views/thoriumcorp_menu.xml',
        'views/thoriumcorp_patient.xml',
        'views/medical_center.xml',
        'views/thoriumcorp_lab_view.xml',
        'data/thoriumcorp_lab_sequences.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'maintainer': 'Julio César Méndez <mendezjcx@thoriumcorp.website>'
}
