{
    "name": "Odoo Shell Terminal",
    "version": "19.0.1.0.0",
    "summary": """
    Browser-based Odoo shell and live log viewer in a systray floating panel
    """,
    "category": "Technical",
    "author": "Mihran Thalhath",
    "website": "https://github.com/MihranThalhath",
    "depends": ["web", "base"],
    "data": [
        "security/shell_terminal_groups.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "odoo_shell_terminal/static/src/components/**/*.js",
            "odoo_shell_terminal/static/src/components/**/*.xml",
            "odoo_shell_terminal/static/src/components/**/*.scss",
        ],
    },
    "images": ["static/description/banner.png"],
    "installable": True,
    "application": False,
    "license": "OPL-1",
}
