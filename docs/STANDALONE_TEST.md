# Standalone-mode verification — Phase 3 #17

Documents the test that confirms the wall-mounted bridge keeps
working when Home Assistant is unreachable. Required by #17's
acceptance criterion.

## Why this matters

The fixture is reachable only via BLE, and the BLE link is owned
exclusively by the ESP32 bridge. If HA goes down (server reboot,
network outage, integration crash), users walking up to the
poolside touchscreen still need to be able to drive the light.
The LVGL UI must therefore be self-sufficient: every on-screen
action must dispatch directly to the BLE component, not through
HA round-trips.

## Test procedure

1. **Confirm baseline.** Bridge is online, HA shows `light.pool_light`,
   the touchscreen is responsive, status-bar icons are all green.
2. **Take HA offline.** Pick whichever is easier:
   - Stop the HA Core service from CLI (`ha core stop`)
   - Disable the ESPHome integration in HA's UI
   - Pull HA off the network (or network-isolate the bridge from HA)
3. **Wait ~10 s** for the API status icon on the touchscreen to
   transition from green → grey. The Wi-Fi and BLE icons should
   stay green.
4. **Exercise every on-screen control:**
   - On/off switch → fixture goes Standby and back on
   - Each of the 5 colour swatches → fixture changes to that
     colour
   - Effect dropdown → pick a show, fixture runs it
   - Lock button → press during a show; verify subsequent Return
     replays the captured colour
   - Return button → fixture comes back to last-locked
5. **Bring HA back online.** Confirm the API icon goes green
   within ~10 s. Pick a colour from HA — verify the touchscreen
   reflects the change (`light.on_state` lambda updates the
   widgets).

## Run results

Fill in after running the procedure.

| Step | Expected | Observed |
|---|---|---|
| Baseline status icons | All green | _TBD_ |
| API offline → status icon | Goes grey within 10 s | _TBD_ |
| Switch off → fixture | Goes Standby | _TBD_ |
| Switch on → fixture | Resumes last preset | _TBD_ |
| Each colour swatch | Drives that colour | _TBD_ |
| Each show effect | Drives that show | _TBD_ |
| Lock + Return | Save/recall works | _TBD_ |
| API back online | Icon back to green | _TBD_ |
| HA-initiated change | Reflects on screen | _TBD_ |

## Notes

_Anything that didn't go as expected. Leave empty if everything
worked._

## Acceptance

- [ ] Status bar reflects real state within ~1 s of change
- [ ] Every on-screen action drives the fixture even with HA offline
- [ ] HA-initiated changes flow back to the touchscreen when reconnected
