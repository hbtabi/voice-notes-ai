"""voice-notes-ai: meeting audio or transcripts -> summary, decisions and action items."""

from .analyse import ActionItem, MeetingNotes, analyse
from .transcript import Segment, Transcript, load_transcript, parse_text

__all__ = ["ActionItem", "MeetingNotes", "Segment", "Transcript", "analyse", "load_transcript", "parse_text"]
__version__ = "0.1.0"
