from __future__ import annotations

import json
import os
import ssl
import threading
from pathlib import Path

# Android SSL Certificate Error Fix
try:
    ssl._create_default_https_context = ssl._create_unverified_context
except Exception:
    pass

from dotenv import load_dotenv
from kivy.clock import Clock
from kivy.core.window import Window
from kivy.metrics import dp
from kivy.utils import platform
from kivymd.app import MDApp
from kivymd.uix.boxlayout import MDBoxLayout
from kivymd.uix.button import MDFlatButton, MDRaisedButton
from kivymd.uix.label import MDLabel
from kivymd.uix.scrollview import MDScrollView
from kivymd.uix.textfield import MDTextField

from core.automation import DesktopAutomation
from core.brain import GeminiBrain
from core.coder import AutonomousCoder
from core.history import ChatHistory
from core.voice import VOICE_OPTIONS, VoiceSystem, normalize_voice_command

# Keyboard opening and soft input adjustment fix
Window.softinput_mode = "below_target"

APP_DIR = Path(__file__).resolve().parent
ANDROID = platform == "android"

# YAHAN APNI GEMINI API KEY ENTER KAREIN
DEFAULT_API_KEY = "YOUR_GEMINI_API_KEY_HERE"


class KhulaApp(MDApp):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.project_dir = APP_DIR / "agent_workspace"
        self._request_in_progress = False
        self._voice_enabled = True
        self._voice_stop = threading.Event()
        self._voice_active = threading.Event()
        self._voice_speaking = threading.Event()
        self._voice_active.set()
        self._voice = VoiceSystem()
        self._voice_name = VOICE_OPTIONS[0]
        self._chat_labels: list[MDLabel] = []
        self._api_key_dialog = None
        self._native_speech_bound = False

    def build(self):
        self.title = "KHULA JARVIS"
        self.theme_cls.theme_style = "Dark"
        self.theme_cls.primary_palette = "Teal"
        self.theme_cls.accent_palette = "Blue"

        data_dir = Path(self.user_data_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        self.project_dir = data_dir / "agent_workspace"
        self.project_dir.mkdir(parents=True, exist_ok=True)
        self.history = ChatHistory(data_dir / "chat_history.json")
        if ANDROID:
            os.environ["KHULA_USE_GEMINI_REST"] = "1"
        self.brain = GeminiBrain()
        self.brain.env_path = data_dir / ".env"
        load_dotenv(self.brain.env_path, override=True)

        # Default API Key set karna agar pehle se .env me na ho
        if not os.getenv("GEMINI_API_KEY"):
            os.environ["GEMINI_API_KEY"] = DEFAULT_API_KEY

        self.brain.reload_credentials()
        self.coder = AutonomousCoder(self.brain)
        self.automation = DesktopAutomation(data_dir)

        root = MDBoxLayout(orientation="vertical", padding=dp(8), spacing=dp(6))
        header = MDBoxLayout(orientation="horizontal", size_hint_y=None, height=dp(48), spacing=dp(6))
        header.add_widget(MDLabel(
            text="KHULA JARVIS", font_style="H6", bold=True,
            halign="left", valign="middle",
        ))
        header.add_widget(MDFlatButton(text="API KEY", on_release=self.open_api_key))
        header.add_widget(MDFlatButton(text="NEW", on_release=self.new_chat))
        root.add_widget(header)

        self.status = MDLabel(
            text="Ready. Ask KHULA anything!",
            size_hint_y=None, height=dp(28), theme_text_color="Secondary",
            halign="left", valign="middle",
        )
        root.add_widget(self.status)

        self.messages = MDBoxLayout(
            orientation="vertical", size_hint_y=None, spacing=dp(10), padding=dp(4),
        )
        self.messages.bind(minimum_height=self.messages.setter("height"))
        scroll = MDScrollView(do_scroll_x=False)
        scroll.add_widget(self.messages)
        root.add_widget(scroll)
        self.scroll = scroll

        # Layout & Keyboard Voice Input (Gboard) Fix
        composer = MDBoxLayout(
            orientation="horizontal", size_hint_y=None, height=dp(60), spacing=dp(4), padding=[dp(2), dp(2), dp(2), dp(2)]
        )
        self.prompt_field = MDTextField(
            hint_text="Message KHULA...",
            mode="rectangle", multiline=False,
            keyboard_suggestions=True,  # Gboard Voice Input Enable Fix
            size_hint_x=0.52,
        )
        self.prompt_field.bind(on_text_validate=self.submit)
        composer.add_widget(self.prompt_field)

        self.mic_button = MDFlatButton(
            text="MIC ON", size_hint_x=0.24, on_release=self.toggle_voice
        )
        composer.add_widget(self.mic_button)

        send_button = MDRaisedButton(
            text="SEND", size_hint_x=0.24, on_release=self.submit
        )
        composer.add_widget(send_button)
        root.add_widget(composer)

        self._restore_history()
        Clock.schedule_once(lambda _dt: self._start_voice_listener(), 0)
        return root

    def on_start(self) -> None:
        if ANDROID:
            self._request_android_permissions()

    def on_stop(self) -> None:
        self._voice_stop.set()
        self._voice_active.clear()
        self._unbind_android_speech()

    def _restore_history(self) -> None:
        for item in self.history.active_chat.get("messages", []):
            speaker = "You" if item.get("role") == "user" else "KHULA"
            self._append_message(speaker, str(item.get("text", "")))

    def _append_message(self, speaker: str, text: str) -> None:
        label = MDLabel(
            text=f"[b]{speaker}[/b]\n{text}",
            markup=True,
            size_hint_y=None,
            halign="left",
            valign="middle",
            padding=(dp(12), dp(10)),
        )
        label.bind(width=lambda widget, width: setattr(widget, "text_size", (width - dp(24), None)))
        label.bind(texture_size=lambda widget, size: setattr(widget, "height", size[1] + dp(24)))
        self.messages.add_widget(label)
        self._chat_labels.append(label)
        
        # Auto scroll to bottom
        Clock.schedule_once(lambda _dt: setattr(self.scroll, "scroll_y", 0), 0.15)

    def _set_status(self, text: str) -> None:
        self.status.text = text

    def new_chat(self, *_args) -> None:
        self.history.new_chat()
        self.messages.clear_widgets()
        self._chat_labels.clear()
        self._set_status("New chat")

    def submit(self, *_args) -> None:
        prompt = self.prompt_field.text.strip()
        if not prompt:
            return
        self.prompt_field.text = ""
        self._submit_prompt(prompt)

    def _submit_prompt(self, prompt: str, voice_origin: bool = False) -> None:
        if prompt.strip().casefold().startswith("/code ") and not voice_origin:
            self._confirm_coding_task(prompt)
            return
        self._begin_prompt(prompt, voice_origin)

    def _confirm_coding_task(self, prompt: str) -> None:
        from kivymd.uix.dialog import MDDialog

        dialog = MDDialog(
            title="Run coding task?",
            text=(
                "KHULA will edit files only inside its selected workspace and run detected "
                "build/tests. Project build and test hooks may execute code."
            ),
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *_: dialog.dismiss()),
                MDRaisedButton(
                    text="RUN",
                    on_release=lambda *_: (
                        dialog.dismiss(),
                        self._begin_prompt(prompt, voice_origin=False),
                    ),
                ),
            ],
        )
        dialog.open()

    def _begin_prompt(self, prompt: str, voice_origin: bool) -> None:
        if self._request_in_progress:
            self._set_status("KHULA is working. Please wait for the current task.")
            return
        self._request_in_progress = True
        self._append_message("You", prompt)
        self.history.add_message("user", prompt)
        self._set_status("Working...")
        threading.Thread(
            target=self._handle_prompt,
            args=(prompt, voice_origin),
            daemon=True,
        ).start()

    def _handle_prompt(self, prompt: str, voice_origin: bool) -> None:
        try:
            self.brain.reload_credentials()
            lowered = prompt.strip().casefold()
            if lowered.startswith("/code "):
                result = self.coder.run(prompt[6:].strip(), self.project_dir)
            elif lowered == "/files":
                result = self.automation.list_files(self.project_dir)
            elif lowered == "/processes":
                if ANDROID:
                    result = "Process listings are not available on Android."
                else:
                    result = self.automation.list_processes()
            elif lowered.startswith("/open "):
                result = self.automation.open_application(prompt[6:].strip())
            elif lowered.startswith("/openfile "):
                result = self.automation.open_project_file(self.project_dir, prompt[10:].strip())
            elif lowered.startswith("/shortcut "):
                result = self.automation.send_shortcut(prompt[10:].strip())
            elif lowered == "/screen":
                result = "Screen capture is not available in the mobile app."
            else:
                # System Prompt: Strictly Hindi (Devnagri Script) Mode
                hindi_instruction = (
                    "System Instruction: You are KHULA JARVIS. Always respond in proper Devnagri Hindi script (देवनागरी हिंदी) "
                    "whenever the user asks questions or requests responses in Hindi. Do not write Hindi using English/Latin alphabet. "
                    "Use pure Devnagri script (जैसे: नमस्ते, मैं आपकी क्या सहायता कर सकता हूँ?).\n\n"
                    f"User Message: {prompt}"
                )
                result = self.brain.ask(hindi_instruction)
        except Exception as exc:
            result = f"Error: {exc}"
        Clock.schedule_once(lambda _dt: self._finish_response(result, voice_origin), 0)

    def _finish_response(self, response: str, speak: bool = False) -> None:
        self._request_in_progress = False
        self._append_message("KHULA", response)
        self.history.add_message("assistant", response)
        self._set_status("Ready")
        # Har jawaab bol kar sunane ke liye
        if speak or self._voice_enabled:
            self._speak_response(response)

    def open_api_key(self, *_args) -> None:
        from kivymd.uix.dialog import MDDialog

        self._api_key_field = MDTextField(
            hint_text="Gemini API key",
            password=True,
            text=os.getenv("GEMINI_API_KEY", ""),
        )
        self._api_key_dialog = MDDialog(
            title="Gemini API key",
            type="custom",
            content_cls=self._api_key_field,
            buttons=[
                MDFlatButton(text="CANCEL", on_release=lambda *_: self._api_key_dialog.dismiss()),
                MDFlatButton(text="SAVE", on_release=self._save_api_key),
            ],
        )
        self._api_key_dialog.open()

    def _save_api_key(self, *_args) -> None:
        key = self._api_key_field.text.strip()
        if not key or "\n" in key or "\r" in key:
            self._set_status("Enter a valid API key.")
            return
        env_path = Path(self.user_data_dir) / ".env"
        env_path.write_text(f"GEMINI_API_KEY={json.dumps(key)}\n", encoding="utf-8")
        os.environ["GEMINI_API_KEY"] = key
        self.brain.reload_credentials()
        self._api_key_dialog.dismiss()
        self._set_status("API key saved on this device.")

    def _start_voice_listener(self) -> None:
        if ANDROID:
            self._bind_android_speech()
            return
        threading.Thread(target=self._desktop_voice_worker, daemon=True).start()

    def _desktop_voice_worker(self) -> None:
        try:
            self._voice.listen_continuously(
                self._queue_voice_text,
                self._voice_stop,
                self._voice_active,
                lambda error: Clock.schedule_once(
                    lambda _dt: self._set_status(f"Voice unavailable: {error}"), 0
                ),
            )
        except Exception as exc:
            message = str(exc)
            Clock.schedule_once(lambda _dt: self._set_status(f"Voice unavailable: {message}"), 0)

    def _queue_voice_text(self, text: str) -> None:
        Clock.schedule_once(lambda _dt: self._handle_voice_text(text), 0)

    def _handle_voice_text(self, text: str) -> None:
        if self._voice_enabled and not self._request_in_progress:
            self._submit_prompt(normalize_voice_command(text), voice_origin=True)

    def toggle_voice(self, *_args) -> None:
        if ANDROID:
            self._launch_android_speech()
            return
        self._voice_enabled = not self._voice_enabled
        if self._voice_enabled:
            self._voice_active.set()
        else:
            self._voice_active.clear()
        self.mic_button.text = "MIC ON" if self._voice_enabled else "MIC OFF"
        self._set_status("Voice listener on." if self._voice_enabled else "Microphone paused.")

    def _bind_android_speech(self) -> None:
        try:
            from android.activity import bind
            bind(on_activity_result=self._on_android_speech_result)
            self._native_speech_bound = True
            self._set_status("Tap MIC to speak. Android speech recognition is ready.")
        except Exception:
            self._set_status("Tap MIC to speak to KHULA.")

    def _launch_android_speech(self) -> None:
        if self._request_in_progress:
            self._set_status("KHULA is working. Please wait...")
            return
        try:
            from jnius import autoclass
            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            current_activity = PythonActivity.mActivity

            intent_class = autoclass("android.content.Intent")
            recognizer = autoclass("android.speech.RecognizerIntent")
            intent = intent_class(recognizer.ACTION_RECOGNIZE_SPEECH)
            intent.putExtra(recognizer.EXTRA_LANGUAGE_MODEL, recognizer.LANGUAGE_MODEL_FREE_FORM)
            intent.putExtra(recognizer.EXTRA_PROMPT, "Speak to KHULA JARVIS")
            current_activity.startActivityForResult(intent, 6821)
            self._set_status("Listening...")
        except Exception as exc:
            self._set_status(f"Could not start speech recognition: {exc}")

    def _on_android_speech_result(self, _request_code, result_code, intent) -> None:
        if int(_request_code) != 6821 or intent is None:
            return
        try:
            recognizer = __import__("jnius").autoclass("android.speech.RecognizerIntent")
            results = intent.getStringArrayListExtra(recognizer.EXTRA_RESULTS)
            if results and results.size() > 0:
                spoken = str(results.get(0))
                Clock.schedule_once(
                    lambda _dt: self._submit_prompt(normalize_voice_command(spoken), voice_origin=True),
                    0,
                )
            else:
                Clock.schedule_once(lambda _dt: self._set_status("No speech was recognized."), 0)
        except Exception as exc:
            message = str(exc)
            Clock.schedule_once(lambda _dt: self._set_status(f"Speech result error: {message}"), 0)

    def _unbind_android_speech(self) -> None:
        if self._native_speech_bound:
            try:
                from android.activity import unbind
                unbind(on_activity_result=self._on_android_speech_result)
            except (ImportError, AttributeError):
                pass
            self._native_speech_bound = False

    def _speak_response(self, text: str) -> None:
        threading.Thread(target=self._speech_worker, args=(text,), daemon=True).start()

    def _speech_worker(self, text: str) -> None:
        self._voice_speaking.set()
        self._voice_active.clear()
        try:
            if ANDROID:
                try:
                    from plyer import tts
                    tts.speak(text[:3000])
                except Exception:
                    pass
            else:
                self._voice.speak(text, self._voice_name)
        except Exception as exc:
            message = str(exc)
            Clock.schedule_once(lambda _dt: self._set_status(f"Speech unavailable: {message}"), 0)
        finally:
            self._voice_speaking.clear()
            if self._voice_enabled and not self._voice_stop.is_set():
                self._voice_active.set()

    def _request_android_permissions(self) -> None:
        try:
            from android.permissions import Permission, request_permissions

            request_permissions([Permission.RECORD_AUDIO])
        except ImportError:
            return


def main() -> None:
    KhulaApp().run()


if __name__ == "__main__":
    main()
