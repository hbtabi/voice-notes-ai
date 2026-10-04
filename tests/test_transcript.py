from voicenotes.transcript import fmt_time, load_transcript, parse_subtitles, parse_text, sample_transcript


def test_parse_text_with_timestamps_and_speakers():
    t = parse_text("# Sync\n[00:00:05] Ana: Hello there.\n[00:01:10] Ben: Hi.\ncontinued line\n")
    assert t.title == "Sync"
    assert [s.speaker for s in t.segments] == ["Ana", "Ben"]
    assert t.segments[0].start == 5 and t.segments[0].end == 70
    assert t.segments[1].text == "Hi. continued line"
    assert t.duration == 70


def test_parse_text_without_metadata():
    t = parse_text("just some words\nand more")
    assert len(t.segments) == 1 and t.segments[0].speaker == "Speaker"


def test_parse_srt_and_vtt(tmp_path):
    srt = load_transcript(__import__("pathlib").Path(__file__).parents[1] / "examples" / "standup.srt")
    assert srt.speakers == ["Leo", "Sana"] and srt.segments[2].start == 12.5
    vtt = parse_subtitles("WEBVTT\n\n00:01.000 --> 00:04.000\n<v Maya>Ship it on <b>Monday</b>.</v>\n")
    assert vtt.segments[0].speaker == "Maya" and vtt.segments[0].text == "Ship it on Monday."


def test_talk_share_and_sample():
    t = sample_transcript()
    share = t.talk_share()
    assert abs(sum(share.values()) - 1) < 1e-9
    assert set(t.speakers) == {"Amira", "Daniel", "Priya", "Tom"}


def test_fmt_time():
    assert fmt_time(65) == "01:05" and fmt_time(3725) == "01:02:05"
