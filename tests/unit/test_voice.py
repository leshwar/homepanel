"""Voice commands: the rules-based parser (sentences → generic commands) and the runner that sends
them through the normal service pipeline. The home below is made by hand, so nothing here depends on
a brand: names, kinds, rooms, capabilities and device.meta are all the parser gets."""
import asyncio
import shutil
import tempfile
import unittest

from app.core.adapter import Action, AdapterError, Cap, Clean, Device, Key, Kind
from app.core.service import HomeService
from app.core.voice import Home, RulesParser, normalize

LIGHT = [Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR, Cap.COLOR_TEMP]
TV = [Cap.POWER, Cap.VOLUME, Cap.VOLUME_LEVEL, Cap.MUTE, Cap.CHANNEL, Cap.REMOTE, Cap.MEDIA, Cap.APPS, Cap.INPUTS]
APPS = [{"id": "yt.app", "name": "YouTube"}, {"id": "nfx", "name": "Netflix"}, {"id": "dplus", "name": "Disney+"},
        {"id": "pv", "name": "Prime Video"}]
INPUTS = [{"id": "HDMI_1", "name": "HDMI 1"}, {"id": "HDMI_2", "name": "HDMI 2"}, {"id": "tv", "name": "Live TV"}]
VACUUM = [Cap.CLEAN, Cap.DOCK, Cap.ROOMS, Cap.SUCTION, Cap.CLEAN_MODE, Cap.STATION, Cap.LOCATE]


def dev(id, name, kind, room, caps, state=None, meta=None, keep_on=False):
    return Device(id=id, adapter="any", name=name, kind=kind, room=room, caps=list(caps),
                  state={"online": True, **(state or {})}, meta=meta or {}, keep_on=keep_on)


def make_home() -> Home:
    return Home(rooms=["Living room", "Bedroom", "Kitchen"], scenes=[
        {"id": "s1", "name": "Movie night", "actions": []},
        {"id": "s2", "name": "Good morning", "actions": []},
    ], devices=[
        dev("ceiling", "Ceiling light", Kind.LIGHT, "Living room", [Cap.POWER, Cap.BRIGHTNESS, Cap.COLOR_TEMP],
            {"on": True, "brightness": 80}),
        dev("floor", "Floor lamp", Kind.LIGHT, "Living room", LIGHT, {"on": True, "brightness": 45}),
        dev("strip", "TV backlight", Kind.LIGHT, "Living room", LIGHT, {"on": False}),
        dev("lrtv", "Living room TV", Kind.TV, "Living room", TV, {"on": True, "volume": 18},
            {"apps": APPS, "inputs": INPUTS}),
        dev("bar", "Sound bar", Kind.SPEAKER, "Living room",
            [Cap.POWER, Cap.VOLUME, Cap.VOLUME_LEVEL, Cap.MUTE, Cap.INPUTS, Cap.SOUND_MODE], {"on": False, "volume": 10},
            {"inputs": [{"id": "bt", "name": "Bluetooth"}, {"id": "opt", "name": "Optical"}],
             "sound_modes": [{"id": "cin", "name": "Cinema"}, {"id": "mus", "name": "Music"}]}),
        dev("bedlamp", "Bedside lamp", Kind.LIGHT, "Bedroom", LIGHT, {"on": False}),
        dev("bdtv", "Bedroom TV", Kind.TV, "Bedroom", TV, {"on": False, "volume": 5}, {"apps": APPS, "inputs": INPUTS}),
        dev("pendant", "Pendant lights", Kind.LIGHT, "Kitchen", [Cap.POWER, Cap.BRIGHTNESS], {"on": False}),
        dev("kettle", "Kettle", Kind.PLUG, "Kitchen", [Cap.POWER], {"on": False}),
        dev("fridge", "Fridge", Kind.PLUG, "Kitchen", [Cap.POWER], {"on": True}, keep_on=True),
        dev("vac", "Robot vacuum", Kind.VACUUM, "", VACUUM, {"activity": "docked"}, {
            "rooms": [{"id": 1, "name": "Living room"}, {"id": 2, "name": "Kitchen"}, {"id": 7, "name": "Den"}],
            "suction_levels": [{"id": "quiet", "name": "Quiet"}, {"id": "max", "name": "Max+"}],
            "clean_modes": [{"id": "v", "name": "Vacuum"}, {"id": "m", "name": "Mop"}],
            "station_actions": [{"id": "empty", "name": "Empty dustbin"}]}),
    ])


def steps(plan):
    out = []
    for s in plan.steps:
        if s.kind == "command":
            out.append((s.device_id, s.action, s.value) if s.repeat == 1 else (s.device_id, s.action, s.value, s.repeat))
        else:
            out.append((s.kind, s.target))
    return out


# sentence → the commands it should become
TABLE = [
    # power, by name, room, kind, synonym, list and pronoun
    ("Turn on the floor lamp", [("floor", Action.POWER, True)]),
    ("switch the kettle on please", [("kettle", Action.POWER, True)]),
    ("Turn off the living room", [("room_off", "Living room")]),
    ("living room off", [("room_off", "Living room")]),
    ("turn off the lounge", [("room_off", "Living room")]),
    ("turn off the kitchen and the bedroom", [("room_off", "Kitchen"), ("room_off", "Bedroom")]),
    ("turn on the kitchen", [("pendant", Action.POWER, True)]),         # a room "on" means its lights
    ("kitchen lights on", [("pendant", Action.POWER, True)]),
    ("turn on the lights in the bedroom", [("bedlamp", Action.POWER, True)]),
    ("turn on the bedroom telly", [("bdtv", Action.POWER, True)]),
    ("Turn the floor lamp on and the kettle off", [("floor", Action.POWER, True), ("kettle", Action.POWER, False)]),
    ("turn off the floor lamp and the backlight", [("floor", Action.POWER, False), ("strip", Action.POWER, False)]),
    ("turn on the backlight and make it blue", [("strip", Action.POWER, True),
                                                 ("strip", Action.COLOR, {"r": 40, "g": 90, "b": 255})]),
    ("turn off the celing light", [("ceiling", Action.POWER, False)]),   # misheard / misspelt
    ("turn off the lamp", [("floor", Action.POWER, False)]),           # only one lamp is on
    # numbers and percentages
    ("set the floor lamp to 30 percent", [("floor", Action.BRIGHTNESS, 30)]),
    ("Set the floor lamp to 30%", [("floor", Action.BRIGHTNESS, 30)]),
    ("set the floor lamp to thirty five percent", [("floor", Action.BRIGHTNESS, 35)]),
    ("floor lamp to a hundred percent", [("floor", Action.BRIGHTNESS, 100)]),
    ("dim the floor lamp", [("floor", Action.BRIGHTNESS, 20)]),
    ("set the floor lamp to max", [("floor", Action.BRIGHTNESS, 100)]),
    # colors and whites
    ("make the backlight blue", [("strip", Action.COLOR, {"r": 40, "g": 90, "b": 255})]),
    ("make the backlight warm white", [("strip", Action.COLOR_TEMP, 2700)]),
    ("set the ceiling light to daylight", [("ceiling", Action.COLOR_TEMP, 6000)]),
    # TV and sound bar
    ("TV volume up", [("lrtv", Action.VOLUME, 23)]),                   # the TV that's on
    ("turn the tv down", [("lrtv", Action.VOLUME, 13)]),
    ("volume up by 10 on the living room tv", [("lrtv", Action.VOLUME, 28)]),
    ("set the bedroom tv volume to twenty", [("bdtv", Action.VOLUME, 20)]),
    ("mute the TV", [("lrtv", Action.MUTE, True)]),
    ("unmute the sound bar", [("bar", Action.MUTE, False)]),
    ("open YouTube", [("lrtv", Action.LAUNCH_APP, "yt.app")]),
    ("put on netflix in the bedroom", [("bdtv", Action.LAUNCH_APP, "nfx")]),
    ("open disney plus on the bedroom tv", [("bdtv", Action.LAUNCH_APP, "dplus")]),
    ("switch to HDMI 2", [("lrtv", Action.SET_INPUT, "HDMI_2")]),
    ("switch the bedroom tv to hdmi two", [("bdtv", Action.SET_INPUT, "HDMI_2")]),
    ("set the sound bar to cinema mode", [("bar", Action.SET_SOUND_MODE, "cin")]),
    ("switch the soundbar to bluetooth", [("bar", Action.SET_INPUT, "bt")]),
    ("next channel", [("lrtv", Action.CHANNEL_UP, None)]),
    ("pause the tv", [("lrtv", Action.KEY, Key.PAUSE)]),
    # vacuum
    ("start the vacuum", [("vac", Action.CLEAN, Clean.START)]),
    ("start the robot", [("vac", Action.CLEAN, Clean.START)]),
    ("vacuum the house", [("vac", Action.CLEAN, Clean.START)]),
    ("vacuum the kitchen and den", [("vac", Action.CLEAN_ROOMS, [2, 7])]),
    ("clean the living room, the kitchen and the den", [("vac", Action.CLEAN_ROOMS, [1, 2, 7])]),
    ("mop the kitchen", [("vac", Action.SET_CLEAN_MODE, "m"), ("vac", Action.CLEAN_ROOMS, [2])]),
    ("send the vacuum home", [("vac", Action.DOCK, None)]),
    ("send the hoover back to its dock", [("vac", Action.DOCK, None)]),
    ("pause the vacuum", [("vac", Action.CLEAN, Clean.PAUSE)]),
    ("set the vacuum to max", [("vac", Action.SET_SUCTION, "max")]),
    ("empty the dustbin", [("vac", Action.STATION, "empty")]),
    ("find the robot", [("vac", Action.LOCATE, None)]),
    # scenes, everything, questions
    ("run movie night", [("scene", "s1")]),
    ("Movie night!", [("scene", "s1")]),
    ("good morning", [("scene", "s2")]),
    ("turn everything off", [("all_off", None)]),
    ("all off", [("all_off", None)]),
    ("what's on in the bedroom?", [("query", "Bedroom")]),
    ("what's on", [("query", None)]),
]


class ParserTableTests(unittest.TestCase):
    def setUp(self):
        self.home = make_home()
        self.parser = RulesParser()

    def parse(self, text):
        return self.parser.parse_now(text, self.home)

    def test_sentences_become_commands(self):
        for text, want in TABLE:
            with self.subTest(text=text):
                plan = self.parse(text)
                self.assertEqual((plan.error, plan.question), ("", ""))
                self.assertEqual(steps(plan), want)

    def test_parse_is_async_for_other_parsers(self):
        plan = asyncio.run(self.parser.parse("turn on the kettle", self.home))
        self.assertEqual(steps(plan), [("kettle", Action.POWER, True)])


class ParserAmbiguityTests(unittest.TestCase):
    def setUp(self):
        self.home = make_home()
        self.parser = RulesParser()

    def test_which_lamp(self):
        plan = RulesParser().parse_now("set the lamp to 30 percent", self.home)
        self.assertEqual(plan.steps, [])
        self.assertEqual(plan.question, "Which lamp?")
        self.assertEqual([c.label for c in plan.choices], ["Floor lamp", "Bedside lamp"])
        self.assertEqual([c.detail for c in plan.choices], ["Living room", "Bedroom"])
        # each choice is a sentence that now names one device
        picked = RulesParser().parse_now(plan.choices[1].text, self.home)
        self.assertEqual(steps(picked), [("bedlamp", Action.BRIGHTNESS, 30)])

    def test_which_tv_when_none_is_on_and_choices_keep_the_rest_of_the_sentence(self):
        self.home.devices[3].state["on"] = False
        plan = self.parser.parse_now("turn off the kettle and open youtube", self.home)
        self.assertEqual(plan.question, "Which TV?")
        self.assertEqual([c.label for c in plan.choices], ["Living room TV", "Bedroom TV"])
        picked = self.parser.parse_now(plan.choices[1].text, self.home)
        self.assertEqual(steps(picked), [("kettle", Action.POWER, False), ("bdtv", Action.LAUNCH_APP, "yt.app")])

    def test_nothing_named_asks_between_the_devices_that_can(self):
        plan = self.parser.parse_now("volume 20", self.home)    # TV on, sound bar off: the TV
        self.assertEqual(steps(plan), [("lrtv", Action.VOLUME, 20)])
        self.home.devices[4].state["on"] = True
        plan = self.parser.parse_now("volume 20", self.home)
        self.assertEqual([c.label for c in plan.choices], ["Living room TV", "Sound bar"])
        self.assertEqual(steps(self.parser.parse_now(plan.choices[1].text, self.home)), [("bar", Action.VOLUME, 20)])

    def test_same_name_in_two_rooms(self):
        self.home.devices.append(dev("lamp2", "Floor lamp", Kind.LIGHT, "Bedroom", LIGHT, {"on": True}))
        plan = self.parser.parse_now("dim the floor lamp", self.home)
        self.assertEqual([(c.label, c.detail) for c in plan.choices], [("Floor lamp", "Living room"), ("Floor lamp", "Bedroom")])
        self.assertEqual(steps(self.parser.parse_now(plan.choices[1].text, self.home)), [("lamp2", Action.BRIGHTNESS, 35)])

    def test_turn_on_picks_the_lamp_that_is_off(self):
        self.assertEqual(steps(self.parser.parse_now("turn on the lamp", self.home)), [("bedlamp", Action.POWER, True)])


class ParserSafetyTests(unittest.TestCase):
    def setUp(self):
        self.home = make_home()
        self.parser = RulesParser()

    def test_everything_off_needs_a_yes(self):
        plan = self.parser.parse_now("turn everything off", self.home)
        self.assertEqual(plan.confirm, "Turn off everything? 3 devices are on.")    # the fridge stays on

    def test_turning_off_a_keep_on_device_needs_a_yes(self):
        plan = self.parser.parse_now("turn off the fridge", self.home)
        self.assertEqual(steps(plan), [("fridge", Action.POWER, False)])
        self.assertIn("set to stay on", plan.confirm)

    def test_a_group_off_leaves_keep_on_devices_alone(self):
        plan = self.parser.parse_now("turn off the plugs", self.home)
        self.assertEqual(steps(plan), [("kettle", Action.POWER, False)])
        self.assertEqual(plan.confirm, "")
        self.assertIn("Left the Fridge on", plan.notes[0])

    def test_everything_on_is_refused(self):
        self.assertIn("won't turn everything on", self.parser.parse_now("turn everything on", self.home).error)

    def test_normal_commands_need_no_yes(self):
        self.assertEqual(self.parser.parse_now("turn off the kitchen", self.home).confirm, "")


class ParserUnknownTests(unittest.TestCase):
    def setUp(self):
        self.home = make_home()
        self.parser = RulesParser()

    def test_unknown_phrases_say_so(self):
        for text, said in [
            ("blah blah", "don't know how to “blah blah”"),
            ("turn on the garage", "couldn't find “garage”"),
            ("run party time", "don't know a scene called “party time”"),
            ("turn it off", "not sure what “it” is"),
            ("make the ceiling light blue", "The Ceiling light can only change its shade of white"),
            ("mute the kettle", "The Kettle can't do that"),
            ("vacuum the garage", "doesn't know a room called “garage”. Its rooms are Living room, Kitchen and Den"),
            ("", "didn't catch anything"),
        ]:
            with self.subTest(text=text):
                plan = self.parser.parse_now(text, self.home)
                self.assertEqual(plan.steps, [])
                self.assertIn(said, plan.error)

    def test_a_known_part_still_runs_and_the_rest_is_explained(self):
        plan = self.parser.parse_now("turn on the kettle and turn on the garage", self.home)
        self.assertEqual(steps(plan), [("kettle", Action.POWER, True)])
        self.assertEqual(plan.notes, ["I couldn't find “garage”."])

    def test_an_unknown_vacuum_room_is_left_out(self):
        plan = self.parser.parse_now("vacuum the kitchen and the garage", self.home)
        self.assertEqual(steps(plan), [("vac", Action.CLEAN_ROOMS, [2])])
        self.assertEqual(plan.notes, ["It doesn't know “garage”, so I left that out."])


class NormalizeTests(unittest.TestCase):
    def test_numbers_and_words(self):
        self.assertEqual(normalize("Set the lamp to Thirty-Five %!"), "set the lamp to 35 percent")
        self.assertEqual(normalize("HDMI2"), "hdmi 2")
        self.assertEqual(normalize("one hundred per cent"), "100 percent")
        self.assertEqual(normalize("Disney+"), "disney plus")
        self.assertEqual(normalize("the sound bar, then the T.V."), "the soundbar and then the tv")
        self.assertEqual(normalize("What's on?"), "whats on")


class VoiceServiceTests(unittest.IsolatedAsyncioTestCase):
    """Voice.handle() on the demo home: runs through HomeService and its middleware."""

    async def asyncSetUp(self):
        self.dir = tempfile.mkdtemp()
        self.svc = HomeService(self.dir, demo=True)
        await self.svc.start()
        for d in list(self.svc.store.devices):   # the first poll, so it can't overwrite the commands below
            await self.svc.refresh(d)

    async def asyncTearDown(self):
        await self.svc.stop()
        shutil.rmtree(self.dir, ignore_errors=True)

    async def test_runs_commands_and_says_what_it_did(self):
        r = await self.svc.voice.handle("turn on the kettle and set the bedside lamp to 30 percent")
        self.assertTrue(r["understood"])
        self.assertEqual(r["say"], "Turned on the Kettle plug and set the Bedside lamp to 30%.")
        self.assertTrue(self.svc.get("kt-kettle").state["on"])
        self.assertEqual(self.svc.get("bd-lamp").state["brightness"], 30)
        self.assertEqual([(d["device_id"], d["action"]) for d in r["done"]],
                         [("kt-kettle", "power"), ("bd-lamp", "brightness")])

    async def test_voice_goes_through_the_middleware(self):
        seen = []

        async def no_kettle(ctx, call_next):         # e.g. an access rule from another feature
            seen.append((ctx.device.id, ctx.action))
            if ctx.device.id == "kt-kettle":
                raise AdapterError("You can't use the kettle.")
            return await call_next(ctx)

        self.svc.use(no_kettle, index=0)
        r = await self.svc.voice.handle("turn on the kettle and the bedside lamp")
        self.assertEqual(seen, [("kt-kettle", "power"), ("bd-lamp", "power")])
        self.assertEqual(r["failed"], [{"device_id": "kt-kettle", "action": "power", "error": "You can't use the kettle."}])
        self.assertEqual(r["say"], "Turned on the Bedside lamp. You can't use the kettle.")
        self.assertFalse(self.svc.get("kt-kettle").state.get("on"))

    async def test_everything_off_waits_for_a_yes(self):
        r = await self.svc.voice.handle("turn everything off")
        self.assertTrue(r["confirm"].startswith("Turn off everything?"))
        self.assertTrue(self.svc.get("lr-ceiling").state["on"])        # nothing happened yet
        r = await self.svc.voice.handle("turn everything off", confirm=True)
        self.assertRegex(r["say"], r"^Turned off \d+ devices\.$")
        self.assertFalse(self.svc.get("lr-ceiling").state["on"])

    async def test_question_and_choices(self):
        r = await self.svc.voice.handle("set the lamp to 30%")
        self.assertEqual((r["question"], r["say"]), ("Which lamp?", "Which lamp?"))
        self.assertEqual([c["label"] for c in r["choices"]], ["Floor lamp", "Bedside lamp"])
        r = await self.svc.voice.handle(r["choices"][0]["text"])
        self.assertEqual(r["say"], "Set the Floor lamp to 30%.")

    async def test_scene_room_and_status(self):
        r = await self.svc.voice.handle("run movie night")
        self.assertEqual(r["say"], "Ran Movie night.")
        r = await self.svc.voice.handle("what's on in the kitchen")
        self.assertEqual(r["say"], "On in the Kitchen: the Fridge plug.")
        r = await self.svc.voice.handle("turn off the living room")
        self.assertRegex(r["say"], r"^Turned off \d devices in the Living room\.$")
        r = await self.svc.voice.handle("what's on in the living room?")
        self.assertEqual(r["say"], "Nothing is on in the Living room.")

    async def test_vacuum(self):
        r = await self.svc.voice.handle("vacuum the kitchen and den")
        self.assertEqual(r["say"], "Sent the Robot vacuum to clean the Kitchen. It doesn't know “den”, so I left that out.")
        self.assertEqual(self.svc.get("lr-vacuum").state["activity"], "cleaning")
        r = await self.svc.voice.handle("send the vacuum home")
        self.assertEqual(r["say"], "Sent the Robot vacuum home.")

    async def test_not_understood_and_empty(self):
        r = await self.svc.voice.handle("sing me a song")
        self.assertFalse(r["understood"])
        self.assertIn("don't know how", r["say"])
        with self.assertRaises(AdapterError):
            await self.svc.voice.handle("   ")

    async def test_another_parser_can_be_plugged_in(self):
        from app.core.voice import Plan, Step

        class Fixed:
            async def parse(self, text, home):
                assert any(d.id == "kt-kettle" for d in home.devices)
                return Plan(steps=[Step(device_id="kt-kettle", action=Action.POWER, value=True)])

        self.svc.voice.parser = Fixed()
        r = await self.svc.voice.handle("anything at all")
        self.assertEqual(r["say"], "Turned on the Kettle plug.")


if __name__ == "__main__":
    unittest.main()
