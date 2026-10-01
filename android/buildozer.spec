[app]
title = 量化选股
package.name = quantstock
package.domain = org.quant
source.dir = .
source.include_exts = py,png,jpg,kv,atlas
version = 1.0.0
requirements = python3,kivy==2.2.1,requests
orientation = portrait
fullscreen = 0
android.permissions = INTERNET
android.archs = arm64-v8a
android.api = 33
android.minapi = 21
android.accept_sdk_license = True
ios.kivy_icons = no

[buildozer]
log_level = 2
warn_on_root = 1
