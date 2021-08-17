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
        ################################

        This modules includes lab tests:

            * Values
            * Reports
            * PoS
    """,
    'author': "Thorium Corp FP",
    'website': "https://thoirumcorp.website",
    'category': 'Thoriumcorp',
    'version': '13.0.0.0.1',
    'depends': ['base'],
    'data': [
        'views/thoriumcorp_lab_view.xml',
        'data/thoriumcorp_lab_sequences.xml',
    ],
    'demo': [],
    'installable': True,
    'application': True,
    'maintainer': 'Julio César Méndez <mendezjcx@thoriumcorp.website>'
}
