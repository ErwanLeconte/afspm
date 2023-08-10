"""Holds control server, for encapsulating some communication logic."""

import zmq
import logging
from google.protobuf.message import Message

from . import commands as cmd
from ..protos.generated import control_pb2 as ctrl

logger = logging.getLogger(__name__)


class ControlServer:
    """Encapsulates logic for responding to DeviceControl requests.

    The expected functionality is:
    - Within your main loop, call recv() regularly to check for any
    incoming requests.
    - If one was received, handle it appropriately and call reply()
    as soon as possible.

    Attributes:
        server: the REP socket associated with our server
    """

    def __init__(self, url: str, ctx: zmq.Context = None):
        if not ctx:
            ctx = zmq.Context.instance()

        self.server = ctx.socket(zmq.REP)
        self.server.bind(url)

    def poll(self, timeout_ms: int = 1000
             ) -> (ctrl.ControlRequest, Message):
        """Poll for message and return if received.

        We use a poll() first, to ensure there is a message to receive. To do
        a blocking receive, simply set timeout_ms to None.

        Note: recv() *does not* handle KeyboardInterruption exceptions,
        please make sure your calling code does.

        Args:
            timeout_ms: the poll timeout, in milliseconds. If None,
                we do not pull and do a blocking receive instead.

        Returns:
            A tuple consisting of:
            - The ControlRequest received, and
            - The appropriate protobuf message (if applicable; if not, None).
            If no request was received, both will be None.
        """
        msg = None
        if timeout_ms:
            if self.server.poll(timeout_ms, zmq.POLLIN):
                msg = self.server.recv_multipart(zmq.NOBLOCK)
        else:
            msg = self.server.recv_multipart()

        if msg:
            return cmd.parse_request(msg)
        return (None, None)

    def reply(self, rep: ctrl.ControlResponse):
        """Send the reply to a request received.

        This method is expected to be called right after receiving a req.

        Args:
            rep: ctrl.ControlResponse we wish to send as response to the prior
                req received.
        """
        self.server.send(cmd.serialize_response(rep))