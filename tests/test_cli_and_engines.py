import json
import wave
from datetime import date

import pytest

from voicenotes import transcribe as tx
from voicenotes.cli import main
from voicenotes.llm import LLMError, OpenAICompatible, extract_json
from voicenotes.llm_analyse import llm_analyse
from voicenotes.transcript import sample_transcript


def _wav(path, seconds=0.5):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(16000)
        w.writeframes(b"\x00\x00" * int(16000 * seconds))
    return path


@pytest.fixture
def no_engines(monkeypatch):
    monkeypatch.setattr(tx, "engine_status", lambda: [tx.EngineStatus(n, n == "sample", "") for n in
                                                      ("faster-whisper", "whisper", "api", "sample")])


def test_wav_duration(tmp_path):
    assert tx.wav_duration(_wav(tmp_path / "a.wav", 1.25)) == pytest.approx(1.25)
    assert tx.wav_duration(tmp_path / "missing.wav") is None


def test_auto_falls_back_to_sample(tmp_path, no_engines):
    transcript, engine = tx.transcribe(_wav(tmp_path / "a.wav"), engine="auto")
    assert engine == "sample" and transcript.segments


def test_explicit_engine_errors_when_missing(tmp_path, no_engines):
    with pytest.raises(tx.TranscriptionError):
        tx.transcribe(_wav(tmp_path / "a.wav"), engine="api")


def test_backend_is_used_when_available(tmp_path, monkeypatch):
    monkeypatch.setattr(tx, "engine_status", lambda: [tx.EngineStatus("api", True, ""),
                                                      tx.EngineStatus("faster-whisper", False, ""),
                                                      tx.EngineStatus("whisper", False, "")])
    fake = tx.Transcript([tx.Segment("I'll ship it tomorrow.")])
    monkeypatch.setattr(tx, "_api", lambda path: fake)
    assert tx.transcribe(_wav(tmp_path / "a.wav")) == (fake, "api")


def test_cli_demo_json(capsys):
    assert main(["demo", "-f", "json", "--date", "2026-10-05"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["action_items"]) == 7 and data["engine"] == "sample"


def test_cli_process_srt_markdown(tmp_path):
    out = tmp_path / "notes.md"
    src = __import__("pathlib").Path(__file__).parents[1] / "examples" / "standup.srt"
    assert main(["process", str(src), "-f", "md", "-o", str(out), "--date", "2026-10-05"]) == 0
    md = out.read_text()
    assert "| ☐ | Add a disk usage alert on staging | Leo | Thu 08 Oct |" in md
    assert "Review Sana's pull request for the billing page" in md
    assert "move standups" in md


def test_cli_audio_without_engines(tmp_path, no_engines, capsys):
    assert main(["process", str(_wav(tmp_path / "m.wav")), "-f", "json"]) == 0
    assert "bundled sample transcript" in capsys.readouterr().err


def test_cli_missing_file():
    assert main(["process", "nope.txt"]) == 2


def test_extract_json():
    assert extract_json('Sure!\n```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('noise {"b": [1]} trailing') == {"b": [1]}
    with pytest.raises(LLMError):
        extract_json("no json")


class FakeClient(OpenAICompatible):
    def __init__(self, reply):
        super().__init__(api_key="k")
        self.reply = reply

    def chat_json(self, system, user):
        if isinstance(self.reply, Exception):
            raise self.reply
        return self.reply


def test_llm_analyse_maps_fields():
    reply = {"summary": ["Short."], "topics": ["beta"], "decisions": [{"text": "Ship", "speaker": "Amira"}],
             "action_items": [{"task": "Fix crash", "owner": "Daniel", "due": "2026-10-07", "priority": "high"}],
             "questions": []}
    notes = llm_analyse(sample_transcript(), date(2026, 10, 5), client=FakeClient(reply))
    assert notes.analyser.startswith("llm:") and notes.action_items[0].owner == "Daniel"
    assert notes.summary == ["Short."]


def test_llm_analyse_falls_back_on_error():
    notes = llm_analyse(sample_transcript(), date(2026, 10, 5), client=FakeClient(LLMError("down")))
    assert notes.analyser == "rules" and len(notes.action_items) == 7
