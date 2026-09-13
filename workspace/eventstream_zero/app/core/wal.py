import mmap
import os
import struct
import time
import uuid

from pydantic import BaseModel, Field


class MessageHeader(BaseModel):
    uuid: str = Field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: float = Field(default_factory=time.time)
    compression: int = 0
    correlation_id: str = ""
    schema_version: int = 1

class Message(BaseModel):
    header: MessageHeader = Field(default_factory=MessageHeader)
    payload: str

class WALSegment:
    def __init__(self, filepath: str, max_size: int = 10 * 1024 * 1024):
        self.filepath = filepath
        self.max_size = max_size
        self.file = open(filepath, "a+b")
        if os.path.getsize(filepath) == 0:
            self.file.truncate(max_size)
        self.file.flush()
        self.mmap = mmap.mmap(self.file.fileno(), max_size, access=mmap.ACCESS_WRITE)
        self.position = self._find_end()

    def _find_end(self) -> int:
        pos = 0
        while pos < self.max_size:
            length_bytes = self.mmap[pos:pos+4]
            if length_bytes == b'\x00\x00\x00\x00':
                break
            length = struct.unpack(">I", length_bytes)[0]
            if length == 0 or pos + 4 + length > self.max_size:
                break
            pos += 4 + length
        return pos

    def append(self, data: bytes) -> int:
        length = len(data)
        if self.position + 4 + length > self.max_size:
            raise BufferError("Segment full")
        
        self.mmap[self.position:self.position+4] = struct.pack(">I", length)
        self.mmap[self.position+4:self.position+4+length] = data
        offset = self.position
        self.position += 4 + length
        return offset

    def read(self, offset: int) -> bytes | None:
        if offset >= self.position:
            return None
        length_bytes = self.mmap[offset:offset+4]
        if length_bytes == b'\x00\x00\x00\x00':
            return None
        length = struct.unpack(">I", length_bytes)[0]
        return self.mmap[offset+4:offset+4+length]

    def close(self):
        self.mmap.flush()
        self.mmap.close()
        self.file.close()

class WAL:
    def __init__(self, directory: str, topic: str):
        self.directory = directory
        self.topic = topic
        os.makedirs(directory, exist_ok=True)
        self.segments: list[WALSegment] = []
        self._load_segments()

    def _load_segments(self):
        segment_file = os.path.join(self.directory, f"{self.topic}_0.log")
        self.segments.append(WALSegment(segment_file))

    def append(self, message: Message) -> int:
        data = message.model_dump_json().encode("utf-8")
        segment = self.segments[-1]
        try:
            return segment.append(data)
        except BufferError:
            new_idx = len(self.segments)
            segment_file = os.path.join(self.directory, f"{self.topic}_{new_idx}.log")
            new_segment = WALSegment(segment_file)
            self.segments.append(new_segment)
            return new_segment.append(data)

    def read_from(self, offset: int) -> list[Message]:
        segment = self.segments[0]
        messages = []
        pos = offset
        while True:
            data = segment.read(pos)
            if not data:
                break
            msg = Message.model_validate_json(data.decode("utf-8"))
            messages.append(msg)
            pos += 4 + len(data)
        return messages

    def close(self):
        for segment in self.segments:
            segment.close()
