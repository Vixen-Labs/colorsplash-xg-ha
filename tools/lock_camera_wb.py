#!/usr/bin/env python3
"""Lock the white balance / focus / exposure of a camera via AVFoundation
directly (PyObjC), bypassing cv2's broken AUTO_WB property on macOS.

By default it picks the iPhone Continuity Camera (highest-resolution
device whose name contains 'iPhone'). Override with --name.

The lock is applied at the AVCaptureDevice level — settings persist
across AVCaptureSession instances, so a subsequent cv2.VideoCapture()
on the same device should see the locked-WB frames (cv2 opens its own
session under the hood).

Run this once before launching the calibration tool. The lock holds
until the device is reconfigured by another process or unplugged.

Usage:
    python tools/lock_camera_wb.py                  # lock iPhone (default)
    python tools/lock_camera_wb.py --name FaceTime  # lock built-in
    python tools/lock_camera_wb.py --list           # just list devices
"""
from __future__ import annotations

import argparse
import sys
import time

import AVFoundation as AVF
import objc


def list_devices() -> list:
    """Return AVCaptureDevices that produce video."""
    # Modern API: discoverySessionWithDeviceTypes:mediaType:position:
    # avoids the deprecated devicesWithMediaType_.
    types = [
        AVF.AVCaptureDeviceTypeBuiltInWideAngleCamera,
    ]
    # External / Continuity types — try to add but tolerate names that
    # don't exist on older macOS SDKs.
    for name in ("AVCaptureDeviceTypeContinuityCamera",
                 "AVCaptureDeviceTypeExternal",
                 "AVCaptureDeviceTypeExternalUnknown"):
        if hasattr(AVF, name):
            types.append(getattr(AVF, name))
    discovery = AVF.AVCaptureDeviceDiscoverySession.\
        discoverySessionWithDeviceTypes_mediaType_position_(
            types, AVF.AVMediaTypeVideo,
            AVF.AVCaptureDevicePositionUnspecified,
        )
    return list(discovery.devices())


def describe(d) -> str:
    name = d.localizedName()
    typ = d.deviceType()
    return f"  '{name}'  type={typ}  uid={d.uniqueID()}"


def lock(d, settle_seconds: float = 0.0) -> None:
    """Lock white balance, focus, and exposure on device `d`. The
    settings used are the device's current auto-determined values
    at the moment of lock. Optionally sleep `settle_seconds` after
    enabling auto modes so the camera can re-stabilise on the
    current scene before we freeze it."""
    if settle_seconds > 0:
        # Force-enable auto modes briefly so the camera adapts to the
        # current scene before we lock its decisions.
        ok, err = d.lockForConfiguration_(None)
        if not ok:
            raise RuntimeError(
                f"lockForConfiguration failed: {err}",
            )
        try:
            for setter, mode_attr in (
                ("setWhiteBalanceMode_",
                 "AVCaptureWhiteBalanceModeContinuousAutoWhiteBalance"),
                ("setFocusMode_",
                 "AVCaptureFocusModeContinuousAutoFocus"),
                ("setExposureMode_",
                 "AVCaptureExposureModeContinuousAutoExposure"),
            ):
                if d.respondsToSelector_(setter):
                    mode = getattr(AVF, mode_attr)
                    getattr(d, setter)(mode)
            d.unlockForConfiguration()
            print(f"  enabled auto modes; sleeping {settle_seconds:.1f}s "
                  "for adaptation ...")
            time.sleep(settle_seconds)
        except Exception:
            d.unlockForConfiguration()
            raise

    # Now lock the auto-determined values.
    ok, err = d.lockForConfiguration_(None)
    if not ok:
        raise RuntimeError(f"lockForConfiguration failed: {err}")
    try:
        wb_locked = AVF.AVCaptureWhiteBalanceModeLocked
        focus_locked = AVF.AVCaptureFocusModeLocked
        exposure_locked = AVF.AVCaptureExposureModeLocked
        applied = []
        if d.isWhiteBalanceModeSupported_(wb_locked):
            d.setWhiteBalanceMode_(wb_locked)
            applied.append("WB")
        if d.isFocusModeSupported_(focus_locked):
            d.setFocusMode_(focus_locked)
            applied.append("focus")
        if d.isExposureModeSupported_(exposure_locked):
            d.setExposureMode_(exposure_locked)
            applied.append("exposure")
        d.unlockForConfiguration()
        print(f"  LOCKED: {' + '.join(applied)} on '{d.localizedName()}'")
        # Read back current values for diagnostic
        gains = d.deviceWhiteBalanceGains()
        print(f"  WB gains: red={gains.redGain:.3f} "
              f"green={gains.greenGain:.3f} blue={gains.blueGain:.3f}")
    except Exception:
        d.unlockForConfiguration()
        raise


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--name", default="iPhone",
                   help="substring of the camera's localized name "
                        "(default: 'iPhone' for Continuity Camera)")
    p.add_argument("--settle", type=float, default=8.0,
                   help="seconds to let the camera adapt to the scene "
                        "before locking (default 8)")
    p.add_argument("--list", action="store_true",
                   help="list visible devices and exit")
    args = p.parse_args()

    devices = list_devices()
    if not devices:
        print("no AVFoundation video devices found", file=sys.stderr)
        return 1

    print(f"AVFoundation sees {len(devices)} video device(s):")
    for d in devices:
        print(describe(d))
    print()

    if args.list:
        return 0

    needle = args.name.lower()
    matches = [d for d in devices if needle in d.localizedName().lower()]
    if not matches:
        print(f"no device matched name substring '{args.name}'",
              file=sys.stderr)
        return 1
    if len(matches) > 1:
        print(f"warning: {len(matches)} devices matched '{args.name}'; "
              f"using first ('{matches[0].localizedName()}')")
    target = matches[0]

    print(f">>> locking '{target.localizedName()}' ...")
    lock(target, settle_seconds=args.settle)
    print("done. Settings will persist until the device is reconfigured "
          "by another process or unplugged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
