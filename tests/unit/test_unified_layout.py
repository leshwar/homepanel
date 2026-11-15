"""One-way selected-layout consolidation; no network or household fixtures."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from app.core.adapter import AdapterError, Device
from app.core.layout import clean_layout, clean_room_layout, default_layout, migrate_layout, migrate_room_layout, LayoutError
from app.core.profiles import Viewer, current_viewer
from app.core.service import HomeService


def legacy_home():
    return {"version":3,"widgets":[
        {"id":"clock","type":"clock","size":"2x1","hidden":False,"positions":{"6":{"x":0,"y":0,"size":"2x1"}}},
        {"id":"weather","type":"weather","size":"2x1","positions":{"6":{"x":0,"y":3,"size":"2x1"}},
         "overview_positions":{"6":{"x":2,"y":1,"size":"2x1"}}},
        {"id":"zone","type":"zone","size":"1x1","hidden":True,"options":{"tz":"Asia/Kolkata","label":"India"}},
        {"id":"favs","type":"favourites","size":"2x2","options":{"devices":["a","b"]}},
    ]}


class UnifiedLayoutTests(unittest.TestCase):
    def test_selected_overview_moves_clock_and_notifications_into_the_same_grid(self):
        old = legacy_home()
        new = migrate_layout(old,"overview")
        widgets = {w["id"]:w for w in new["widgets"]}
        self.assertEqual(widgets["clock"]["positions"]["6"],{"x":0,"y":0,"size":"3x4"})
        self.assertEqual(widgets["notifications"]["positions"]["6"],{"x":3,"y":0,"size":"3x4"})
        self.assertEqual(widgets["weather"]["positions"]["6"],{"x":2,"y":7,"size":"2x3"})
        self.assertTrue(widgets["zone"]["hidden"])
        self.assertEqual(widgets["zone"]["options"],old["widgets"][2]["options"])
        self.assertEqual(widgets["favs"]["options"],{"devices":["a","b"]})
        self.assertFalse(any("overview_positions" in w for w in new["widgets"]))
        self.assertEqual(migrate_layout(new,"free"),new)
        self.assertEqual(old,legacy_home())
        self.assertEqual(clean_layout(new),new)

    def test_selected_free_keeps_positions_holes_and_custom_height_not_hidden_overview(self):
        new = migrate_layout(legacy_home(),"free")
        widgets = {w["id"]:w for w in new["widgets"]}
        self.assertEqual(widgets["weather"]["positions"]["6"],{"x":0,"y":9,"size":"2x3"})
        self.assertEqual(widgets["clock"]["positions"]["6"],{"x":0,"y":0,"size":"2x3"})
        self.assertEqual(widgets["favs"]["size"],"2x6")
        self.assertEqual(sum(w["type"]=="clock" for w in new["widgets"]),1)
        self.assertEqual(sum(w["type"]=="notifications" for w in new["widgets"]),1)

    def test_hidden_main_clock_stays_hidden_and_empty_free_has_no_resurrected_clock(self):
        old=legacy_home();old["widgets"][0]["hidden"]=True
        self.assertTrue(migrate_layout(old)["widgets"][0]["hidden"])
        new=migrate_layout({"version":3,"widgets":[]},"free")
        self.assertTrue(next(w for w in new["widgets"] if w["type"]=="clock")["hidden"])
        full={"version":3,"widgets":[{"id":f"zone-{i}","type":"zone","size":"1x1"} for i in range(40)]}
        self.assertEqual(len(migrate_layout(full)["widgets"]),42)

    def test_compact_order_is_source_not_unseen_free_coordinates(self):
        old={"version":3,"widgets":[
            {"id":"b","size":"1x1","positions":{"6":{"x":5,"y":20,"size":"1x1"}}},
            {"id":"a","size":"2x2","positions":{"6":{"x":0,"y":5,"size":"2x2"}}},
        ]}
        new=migrate_room_layout(old,[],"compact")
        self.assertEqual([w["id"] for w in new["widgets"]],["b","a"])
        self.assertEqual([w["positions"]["6"] for w in new["widgets"]],
                         [{"x":0,"y":0,"size":"3x3"},{"x":3,"y":0,"size":"3x3"}])
        self.assertEqual([w["positions"]["2"]["y"] for w in new["widgets"]],[0,3])
        self.assertEqual(migrate_room_layout(new,[],"free"),new)
        free=migrate_room_layout(old,[],"free")
        self.assertEqual(free["widgets"][1]["positions"]["6"],{"x":0,"y":15,"size":"2x6"})
        self.assertEqual(clean_room_layout(free),free)

    def test_schema_rejects_clipped_minimums_overlap_and_bad_legacy_data(self):
        for size in ("1x3","2x2","7x4","2x25"):
            with self.subTest(size=size),self.assertRaises(LayoutError):
                clean_layout({"widgets":[{"id":"clock","type":"clock","size":size}]})
        with self.assertRaisesRegex(LayoutError,"overlap"):
            clean_room_layout({"widgets":[{"id":i,"positions":{"2":{"x":0,"y":0,"size":"2x3"}}} for i in ("a","b")]})
        with self.assertRaises(LayoutError):
            migrate_layout({"widgets":[{"id":"clock","type":"clock","positions":[]} ]})
        self.assertEqual(clean_layout(default_layout()),default_layout())

    def test_private_backup_idempotence_profiles_and_stale_edit_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            svc=HomeService(folder)
            svc.store.settings["home_layout"]=legacy_home()
            svc.store.devices["a"]=Device(id="a",adapter="demo",name="TV",kind="tv",caps=["power"],
                                           config={"client_key":"fixture-only"},power_on_screen="home")
            svc.store.profiles=[{"id":"owner","role":"admin","devices":"all","home_view":"free","room_view":"compact",
                                 "home_layout":legacy_home(),"room_layouts":{}},
                                {"id":"member","role":"member","devices":[],"home_view":"overview","home_layout":None}]
            svc.store.save()
            before=Path(svc.store.path).read_bytes()
            svc._migrate_layouts()
            backup=Path(svc.store.path+".layout-v3.bak")
            self.assertEqual(backup.read_bytes(),before)
            self.assertEqual(backup.stat().st_mode & 0o777,0o600)
            saved=Path(svc.store.path).read_bytes()
            original=json.loads(before);current=json.loads(saved)
            for key in ("devices","accounts","rooms","scenes","automations"):
                self.assertEqual(current[key],original[key])
            for p in current["profiles"]:
                self.assertNotIn("home_view",p);self.assertNotIn("room_view",p)
                if p["home_layout"] is not None:
                    self.assertEqual(p["home_layout"]["version"],4)
            self.assertIsNone(current["profiles"][1]["home_layout"])
            svc._migrate_layouts()
            self.assertEqual(Path(svc.store.path).read_bytes(),saved)
            self.assertEqual(backup.read_bytes(),before)
            token=current_viewer.set(Viewer(svc.profiles.get("owner")))
            try:
                entry=copy.deepcopy(svc.layout_for(current_viewer.get()))
                draft=copy.deepcopy(entry);draft["widgets"][0]["hidden"]=True
                svc.save_my_layout(draft,entry)
                with self.assertRaisesRegex(AdapterError,"another screen"):
                    svc.save_my_layout(entry,entry)
            finally:
                current_viewer.reset(token)
