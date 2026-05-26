from odoo.tests.common import TransactionCase


class BaseSynchroTestCase(TransactionCase):
    def setUp(self):
        super().setUp()
        self.server = self.env["base.synchro.server"].create({
            "name": "Test Server",
            "server_url": "127.0.0.1",
            "server_port": 8069,
            "server_db": "test_db",
            "login": "admin",
            "password": "admin",
        })

    def test_server_creation(self):
        self.assertTrue(self.server.active)
        self.assertEqual(self.server.state, "draft")
        self.assertEqual(self.server.node_role, "central")
        self.assertEqual(self.server.conflict_resolution, "newest_wins")

    def test_uuid_get_or_create(self):
        Uuid = self.env["base.synchro.uuid"]
        uuid1 = Uuid.get_or_create("res.partner", 1)
        uuid2 = Uuid.get_or_create("res.partner", 1)
        self.assertEqual(uuid1, uuid2)
        uuid3 = Uuid.get_or_create("res.partner", 2)
        self.assertNotEqual(uuid1, uuid3)

    def test_uuid_find_by_uuid(self):
        Uuid = self.env["base.synchro.uuid"]
        created = Uuid.get_or_create("res.partner", 42)
        found = Uuid.find_by_uuid("res.partner", created)
        self.assertEqual(found, 42)

    def test_uuid_find_by_field(self):
        partner = self.env["res.partner"].create({"name": "Test UUID Find"})
        Uuid = self.env["base.synchro.uuid"]
        found = Uuid.find_by_field("res.partner", "name", "Test UUID Find")
        self.assertEqual(found, partner.id)

    def test_sync_fields_no_avoid(self):
        obj = self.env["base.synchro.obj"].create({
            "name": "Test Partners",
            "domain": "[]",
            "server_id": self.server.id,
            "model_id": self.env.ref("base.model_res_partner").id,
            "action": "d",
        })
        fields = obj.get_sync_fields()
        self.assertIn("name", fields)
        self.assertNotIn("id", fields)
        self.assertNotIn("create_date", fields)

    def test_sync_fields_with_avoid(self):
        obj = self.env["base.synchro.obj"].create({
            "name": "Test Partners",
            "domain": "[]",
            "server_id": self.server.id,
            "model_id": self.env.ref("base.model_res_partner").id,
            "action": "d",
            "avoid_ids": [(0, 0, {"name": "comment"})],
        })
        fields = obj.get_sync_fields()
        self.assertNotIn("comment", fields)
