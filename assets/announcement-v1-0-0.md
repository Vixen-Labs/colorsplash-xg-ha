# Hayward / J&J ColorSplash XG Pool Light Controller bridge

I have a pool light with a Hayward / J&J Electronics ColorSplash XG (LPL-XG-CTRL-1) controller, and I've been frustrated for a while that the only way to control it is Hayward's sad phone app. I have to reconnect to Bluetooth every time I use it, the interface is frustrating, and there's no direct control over RGB colors. If I had a do-over, I would have bought a light with finer color control, but I'm trying to make the best of it.

The fixture itself only offers 5 garish solid colors, and 7 "Shows" that either switch quickly between colors (2 Shows) or blend gradients between several colors (5 Shows). If you want to set the light to any solid color other than the 5 presets, you play one of the Shows, and then hit the "Color Lock" button when it shows a color you like, which saves it in a single "Return" slot that you can then recall directly. No way to enter RGB values. Disappointing design choices, but it gave me _something_ to work with.

With Claude's help, I reverse-engineered the BLE protocol (full protocol notes in the repo for those curious), and built an ESP32 bridge that holds the Bluetooth link to the controller and makes it accessible in Home Assistant over the ESPHome API. After refining it for several weeks, v1.0.0 went out today after a 5-day test with the Bluetooth link held continuously and zero errors logged. Repo here:

https://github.com/Vixen-Labs/colorsplash-xg-ha

In Home Assistant you get `light.pool_light` with on/off plus the 12 hardware effects (5 solid colors and 7 animated Shows), a `select.pool_active_preset` for native scene integration, 5 user preset slots stored on the bridge itself, Lock and Return as buttons, and a handful of diagnostic sensors (RSSI, command count, error count, BLE connected, last command). For the dashboard side there's a custom Lovelace card with an experimental color wheel and preset swatches, plus a stock-YAML version if you'd rather not load custom resources.

The experimental color picker in the card is a "best match via Show-scrub" approximation, based on color analysis of video taken of the animated Shows (something I hope to improve the accuracy of in v1.1). The user presets are saved as a recipe of Show command + time offset for the color lock moment that gives you the color you want.

Happy to answer questions, and if anyone has a ColorSplash XG installed, I'd love to hear how the bridge works for you!