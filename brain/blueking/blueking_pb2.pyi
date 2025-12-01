from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ChatEvent(_message.Message):
    __slots__ = ("username", "message")
    USERNAME_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    username: str
    message: str
    def __init__(self, username: _Optional[str] = ..., message: _Optional[str] = ...) -> None: ...

class ChatResponse(_message.Message):
    __slots__ = ("reply",)
    REPLY_FIELD_NUMBER: _ClassVar[int]
    reply: str
    def __init__(self, reply: _Optional[str] = ...) -> None: ...

class SendChatMessageRequest(_message.Message):
    __slots__ = ("payload",)
    PAYLOAD_FIELD_NUMBER: _ClassVar[int]
    payload: str
    def __init__(self, payload: _Optional[str] = ...) -> None: ...

class SendChatMessageResponse(_message.Message):
    __slots__ = ("status", "error_message")
    class Status(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
        __slots__ = ()
        OK: _ClassVar[SendChatMessageResponse.Status]
        NO_CHAT_CLIENT: _ClassVar[SendChatMessageResponse.Status]
        SEND_FAILED: _ClassVar[SendChatMessageResponse.Status]
    OK: SendChatMessageResponse.Status
    NO_CHAT_CLIENT: SendChatMessageResponse.Status
    SEND_FAILED: SendChatMessageResponse.Status
    STATUS_FIELD_NUMBER: _ClassVar[int]
    ERROR_MESSAGE_FIELD_NUMBER: _ClassVar[int]
    status: SendChatMessageResponse.Status
    error_message: str
    def __init__(self, status: _Optional[_Union[SendChatMessageResponse.Status, str]] = ..., error_message: _Optional[str] = ...) -> None: ...
