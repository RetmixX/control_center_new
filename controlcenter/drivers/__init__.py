from .arduino import BarrierDevice, LampDevice, TerminalDevice
from .base import FEEDBACK_KEYS, Command, Device, DeviceContext
from .robot import RobotDevice
from .udp_legacy import UdpDevice, UdpTransport

DRIVERS = {"robot": RobotDevice, "lamp": LampDevice, "terminal": TerminalDevice, "barrier": BarrierDevice}

__all__ = ["DRIVERS", "FEEDBACK_KEYS", "Command", "Device", "DeviceContext", "UdpDevice", "UdpTransport",
           "RobotDevice", "LampDevice", "TerminalDevice", "BarrierDevice"]
