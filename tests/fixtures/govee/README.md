Recorded answers from Govee's cloud API (`https://openapi.api.govee.com/router/api/v1`)
for an RGBIC TV backlight (H605C), November 2026. The device id is replaced with a fake
one and the scene list is cut to 12 of its 240 scenes. `diy_scenes.json` follows the
shape in Govee's docs (the recorded light had no DIY scenes yet).

| File | Request |
|---|---|
| `user_devices.json` | `GET /user/devices` |
| `scenes.json` | `POST /device/scenes` |
| `diy_scenes.json` | `POST /device/diy-scenes` |
| `state.json` | `POST /device/state` |
