{
    'name': 'CIDA Sync — Sincronización Multi-Sede',
    'version': '19.0.1.0.0',
    'category': 'Technical',
    'summary': 'Sincronización bidireccional entre sedes vía API XML-RPC',
    'description': """
        Módulo de sincronización para la Fundación CIDA.

        Permite sincronizar datos de negocio (contactos, productos, inventario,
        POS) entre dos instancias de Odoo usando la API oficial XML-RPC.

        Características:
        - Sincronización configurable por modelo
        - UUIDs para evitar conflictos de IDs
        - Cola de sincronización con reintentos
        - Resolución de conflictos configurable
        - Log de auditoría completo
        - Cron automático o sync manual
    """,
    'author': 'Fundación CIDA',
    'license': 'LGPL-3',
    'depends': ['base', 'product', 'stock', 'point_of_sale', 'sale_management', 'purchase'],
    'data': [
        'security/ir.model.access.csv',
        'data/sync_rules_data.xml',
        'data/cron.xml',
        'views/sync_config_views.xml',
        'views/sync_log_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
}
