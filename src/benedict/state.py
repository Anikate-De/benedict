from enum import Enum, auto


class State(Enum):
    IDLE = auto()
    STARTING = auto()
    RECORDING = auto()
    FINALIZING = auto()
    INSERTING = auto()
    ERROR = auto()
