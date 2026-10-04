[app]

title = KHULA JARVIS
package.name = khulajarvis
package.domain = org.khula
source.dir = .
source.include_exts = py,png,jpg,jpeg,kv,atlas,json,txt
source.exclude_dirs = .git,.venv,venv,__pycache__,history,tests,agent_workspace,.khula_backups
version = 1.0.0
requirements = python3,kivy==2.3.1,kivymd==1.2.0,python-dotenv,plyer,pillow
orientation = portrait
fullscreen = 0

android.permissions = INTERNET,RECORD_AUDIO
android.api = 33
android.minapi = 23
android.ndk = 25b
android.ndk_api = 23
android.archs = arm64-v8a
android.accept_sdk_license = True
android.enable_androidx = True

[buildozer]
log_level = 2
warn_on_root = 1
