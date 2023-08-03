""" Test publisher-subscriber logic."""

import pytest
import zmq
import time
import threading

from google.protobuf.message import Message

from afspm.io import cache_logic as cl
from afspm.io import publisher
from afspm.io import subscriber
from afspm.io import pubsubcache

from afspm.generated.python import scan_pb2
from afspm.generated.python import control_pb2


# Fixtures!

@pytest.fixture
def ctx():
    return zmq.Context.instance()


@pytest.fixture
def pub_url():
    return "tcp://127.0.0.1:5555"


@pytest.fixture
def psc_url():
    return "tcp://127.0.0.1:5556"


@pytest.fixture
def cache_kwargs():
    return {"cache_logic": cl.ProtoBasedCacheLogic()}


@pytest.fixture
def pub(pub_url):
    return publisher.Publisher(pub_url,
                               cl.CacheLogic.create_envelope_from_proto)


@pytest.fixture
def topics_scan2d():
    return [cl.CacheLogic.create_envelope_from_proto(scan_pb2.Scan2d())]


@pytest.fixture
def topics_spm_status():
    return [cl.CacheLogic.create_envelope_from_proto(control_pb2.SPMStatus())]


@pytest.fixture
def topics_both():
    return [cl.CacheLogic.create_envelope_from_proto(scan_pb2.Scan2d()),
            cl.CacheLogic.create_envelope_from_proto(control_pb2.SPMStatus())]

@pytest.fixture
def wait_ms():
    return 100


def test_pub(ctx, pub):
    """Confirm we can connect and send messages into the void.

    Messages sent with no subscriber are just shelved. We should get no fail
    messages or error.
    """
    scan = scan_pb2.Scan2d()
    scan.parameters.name = 'john doe'
    pub.send_msg(scan)


def assert_sub_received_proto(sub: subscriber.Subscriber,
                              proto: Message):
    """Confirm a message is received by a subscriber."""
    assert sub.recv()
    assert len(sub.cache[cl.CacheLogic.create_envelope_from_proto(proto)]) == 1
    assert (sub.cache[cl.CacheLogic.create_envelope_from_proto(proto)][0]
            == proto)


def test_pubsub_simple(pub_url, cache_kwargs, ctx, pub, topics_scan2d,
                       topics_spm_status, topics_both, wait_ms):
    """ Test a pub-sub network *without* our pubsubcache.

    We will test that:
    - subscribers receive only messages from the envelopes they
    subscribe.
    - a new subscriber does not receive messages from the cache (since there
    is none).
    - messages sent after a new subscriber are sent properly.
    """

    # Connect 2 subscribers and confirm we can send separate message envelopes.
    sub_scan = subscriber.Subscriber(
        pub_url, cl.extract_proto, topics_scan2d,
        cl.update_cache, ctx,
        extract_proto_kwargs=cache_kwargs,
        update_cache_kwargs=cache_kwargs)
    sub_spm = subscriber.Subscriber(
        pub_url, cl.extract_proto, topics_spm_status,
        cl.update_cache, ctx,
        extract_proto_kwargs=cache_kwargs,
        update_cache_kwargs=cache_kwargs)

    # We need some delay between initializing and sending out the first message
    time.sleep(wait_ms / 1000)  # ms to s

    scan = scan_pb2.Scan2d()
    scan.parameters.name = 'john doe'
    pub.send_msg(scan)

    assert not sub_spm.recv(wait_ms)
    assert_sub_received_proto(sub_scan, scan)

    spm = control_pb2.SPMStatus()
    spm.control_mode = control_pb2.ControlMode.CM_PROBLEM
    spm.problems_list.append(
        control_pb2.ExperimentProblem.EP_TIP_SHAPE_CHANGED)
    spm.scan_state = control_pb2.ScanState.SS_FREE

    pub.send_msg(spm)

    assert not sub_scan.recv(wait_ms)
    assert_sub_received_proto(sub_spm, spm)

    # Connect a 3rd subscriber and confirm we *do not* re-receive the old
    # messages (since we do not have a pubsubcache setup).
    sub_both = subscriber.Subscriber(
        pub_url, cl.extract_proto, topics_both,
        cl.update_cache, ctx,
        extract_proto_kwargs=cache_kwargs,
        update_cache_kwargs=cache_kwargs)

    assert not sub_scan.recv(wait_ms)
    assert not sub_spm.recv(wait_ms)
    assert not sub_both.recv(wait_ms)

    # Send a scan again, confirm both and sub_scan receive
    pub.send_msg(scan)
    assert not sub_spm.recv(wait_ms)
    assert_sub_received_proto(sub_both, scan)
    assert_sub_received_proto(sub_scan, scan)


def pubsubcache_routine(psc_url, pub_url, ctx):
    """Routine to create and run a pubsubcache."""
    cache_kwargs = {'cache_logic': cl.ProtoBasedCacheLogic()}
    psc = pubsubcache.PubSubCache(psc_url, pub_url,
                                  cl.extract_proto,
                                  cl.CacheLogic.create_envelope_from_proto,
                                  cl.update_cache, ctx,
                                  extract_proto_kwargs=cache_kwargs,
                                  update_cache_kwargs=cache_kwargs)

    while True:
        psc.poll()



def test_pubsubcache(pub_url, psc_url, cache_kwargs, ctx, pub, topics_scan2d,
                     topics_spm_status, topics_both, wait_ms):
    """ Test a pub-sub network *with* our pubsubcache.

    We will test that:
    - subscribers receive only messages from the envelopes they
    subscribe.
    - upon a new subscriber, old cache messages (from each newly subscribed
    envelope) are received by all current subscribers.
    - messages sent after a new subscriber are sent properly.
    """


    thread = threading.Thread(target=pubsubcache_routine,
                              args=(psc_url, pub_url, ctx))
    thread.daemon = True
    thread.start()

    # We need some delay between initializing and sending out the first message
    time.sleep(wait_ms / 1000)  # ms to s

    # Connect 2 subscribers and confirm we can send separate message envelopes.
    sub_scan = subscriber.Subscriber(
        psc_url, cl.extract_proto, topics_scan2d,
        cl.update_cache, ctx,
        extract_proto_kwargs=cache_kwargs,
        update_cache_kwargs=cache_kwargs)
    sub_spm = subscriber.Subscriber(
        psc_url, cl.extract_proto, topics_spm_status,
        cl.update_cache, ctx,
        extract_proto_kwargs=cache_kwargs,
        update_cache_kwargs=cache_kwargs)

    # We need some delay between initializing and sending out the first message
    time.sleep(wait_ms / 1000)  # ms to s

    scan = scan_pb2.Scan2d()
    scan.parameters.name = 'john doe'
    pub.send_msg(scan)

    assert not sub_spm.recv(wait_ms)
    assert_sub_received_proto(sub_scan, scan)

    spm = control_pb2.SPMStatus()
    spm.control_mode = control_pb2.ControlMode.CM_PROBLEM
    spm.problems_list.append(
        control_pb2.ExperimentProblem.EP_TIP_SHAPE_CHANGED)
    spm.scan_state = control_pb2.ScanState.SS_FREE

    pub.send_msg(spm)

    assert not sub_scan.recv(wait_ms)
    assert_sub_received_proto(sub_spm, spm)

    # Connect a 3rd subscriber and confirm we *do* re-receive the old
    # messages (since we have a pubsubcache setup).
    sub_both = subscriber.Subscriber(
        psc_url, cl.extract_proto, topics_both,
        cl.update_cache, ctx,
        extract_proto_kwargs=cache_kwargs,
        update_cache_kwargs=cache_kwargs)

    assert sub_scan.recv(wait_ms)
    assert sub_spm.recv(wait_ms)
    assert sub_both.recv(wait_ms)

    # Send a scan again, confirm both and sub_scan receive
    pub.send_msg(scan)
    assert not sub_spm.recv(wait_ms)
    assert_sub_received_proto(sub_both, scan)
    assert_sub_received_proto(sub_scan, scan)
