{
    "name": "Multi-DB Synchronization",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "license": "AGPL-3",
    "summary": "Multi-DB Synchronization",
    "author": "OpenERP SA, Serpent Consulting Services Pvt. Ltd., Fundación CIDA",
    "website": "http://www.serpentcs.com",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "data/cron.xml",
        "wizard/base_synchro_view.xml",
        "views/base_synchro_view.xml",
        "views/base_synchro_log_view.xml",
        "views/res_request_view.xml",
    ],
    "installable": True,
}
