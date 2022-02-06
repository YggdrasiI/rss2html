#!/usr/bin/python3
# -*- coding: utf-8 -*-

# Creates a Process pool for actions called by the RSS server.
#
# • Immidealty thrown errors by the actions will provided to the user
# • Errors thrown after N seconds will be logged, only.
# • Number of actions (M) and max time (T) for every action can set.
#
#   Note that running task will not be killed after T seconds, but
#   for each new action procecs we will check the condition
#       '#actions >= M' and '∃process P with T(P) >= T'
#   if true, a new action-process will replace P and
#   otherwise no new action can be created.
#
#  Another variant to kill old/pending prozesses would be Pebble, see
#  https://stackoverflow.com/questions/20991968/asynchronous-multiprocessing-with-a-worker-pool-in-python-how-to-keep-going-aft/31185697#31185697

import os  # for getpid, devnull
from time import time, sleep
from math import ceil
from enum import Enum
from collections import namedtuple
from itertools import count
from subprocess import Popen
import signal
import psutil

import logging
logger = logging.getLogger(__name__)

from queue import Empty
from multiprocessing import Pool, Queue, Lock, TimeoutError # , active_children
from multiprocessing import get_context
from multiprocessing import set_start_method

# For logging in worker processes:
from multiprocessing import get_logger, log_to_stderr
#   Here, not log_to_stderr() is used to avoid double output
# Only the __main__-Thread will overwrites this default
mp_logger = get_logger()
mp_logger.setLevel(logging.DEBUG)

# Add filter to skip messages from multiprocessing package
class JustThisFileFilter(logging.Filter):
    def filter(self, record):
        try:
            return (__file__ in record.pathname)
        except NameError:
            return False
mp_logger.addFilter(JustThisFileFilter())

from feed import Feed

Pending = namedtuple('Pending', ['time', 'result', 'pid'])
ActionPoolState = Enum('ActionPoolState', ['INIT', 'STARTED', 'STOPED'])

N_PROCESSES = 1            # Number of parallel actions (pool size)
ALLOW_ABORT_AFTER = 3.0    # Minimal guaranteed duration
MAX_ACTIVE_OR_PENDING = 2  # Number of actions processed or queue'ed

def _ap_handler():
    mp_logger.debug("ActionPool handler invoked")

    # Get input  data from qIn
    (rid, f, args) = _ap_handler.qIn.get_nowait()

    # Feed qOut-queue with the info that this process got started.
    #mp_logger.debug("Put rid={} in qOut".format(rid))
    _ap_handler.qOut.put_nowait([rid, os.getpid(), time()])
    try:
        ret = f(*args)
    except Exception as e:
        return -1,rid,e,None

    return 0,rid,None,ret


# Workaround that Pool-Process-Arguments can not be a Queue-Object
# See
# https://stackoverflow.com/questions/3827065/can-i-use-a-multiprocessing-queue-in-a-function-called-by-pool-imap/3843313#3843313
def _ap_handler_init(qIn, qOut):
    # Called once in every worker process

    # Init logger in this process
    # mp_logger.debug("Init ActionPool worker process")

    # Propagates queues to handler because you can not use them
    # as arguments in apply_async (queue's not serializable)
    _ap_handler.qIn = qIn
    _ap_handler.qOut = qOut
    # _ap_handler.settings = settings


def kill_children(proc_id, kill_root=False):
    process = psutil.Process(proc_id)
    child_procs = process.children(recursive=False)
    if kill_root:
        child_procs.append(process)

    for child_proc in child_procs:
        logger.debug("Send SIGTERM to child {}".format(child_proc.pid))
        try:
            child_proc.terminate()
        except psutil.NoSuchProcess:
            pass

    gone, alive = psutil.wait_procs(child_procs, timeout=3)
    for child_proc in alive:
        logger.debug("Send SIGKILL to child {}".format(child_proc.pid))
        try:
            child_proc.kill()
        except psutil.NoSuchProcess:
            pass


class ActionPool:

    def __init__(self, settings=None, *,
                 processes=None,
                 max_active_or_pending=None,
                 allow_abort_after=None,
                ):

        # Removed _settings because it is not required now
        # self.settings = _pickable_settings(settings)
        self.processes=processes or N_PROCESSES
        self.max_active_or_pending=max_active_or_pending or MAX_ACTIVE_OR_PENDING
        self.allow_abort_after=allow_abort_after or ALLOW_ABORT_AFTER

        self._pending_lock = Lock()
        self._pending = {}
        self._num_active_or_pending = 0
        self._next_result_id = count()


        # Created in self.start()
        self.pool = None
        self.qIn = None
        self.qOut = None

        # Statistic
        self._counter_ok = []
        self._counter_failed = []
        self._counter_aborted = []
        self._counter_skipped = []

        self._state = ActionPoolState.INIT

    # Define __enter__ and __exit__ for with-statement
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, type, value, traceback):
        # self.wait(timeout=2.0, terminate_workers=True)  # moved into stop()
        self.stop()

    def _close_queues(self):
        # Caling after  pool.close() guarantees that while-loops
        # are finite?!
        #
        # If some action was not started by the pool, qIn
        # contains data.
        try:
            while True:
                d = self.qIn.get_nowait()
                mp_logger.debug("Non consumed data in queue 'qIn': {}".format(d))
        except Empty:
            pass
        finally:
            self.qIn.close()

        try:
            while True:
                d = self.qOut.get_nowait()
                mp_logger.debug("Non consumed data in queue 'qOut': {}".format(d))
        except Empty:
            pass
        finally:
            self.qOut.close()

    def start(self):
        # set_start_method("spawn")  # Too late here....

        if self._state not in [ActionPoolState.INIT, ActionPoolState.STOPED]:
            logger.error("Pool can not be started twice.")
            return

        self.qIn = Queue()  # Sends args to workers
        self.qOut = Queue() # Get results from workers

        # https://stackoverflow.com/a/35134329
        #... but
        # 'This solution is not portable as it works only on Unix.
        #  Moreover, it would not work if the user sets the maxtasksperchild
        #  Pool parameter. The newly created processes would inherit
        #  the standard SIGINT handler again. The pebble library disables
        #  SIGINT by default for the user as soon as the new process is created.'
        if True:
            original_sigint_handler = signal.signal(signal.SIGINT, signal.SIG_IGN)
            self.pool = Pool(processes=self.processes,
                             initializer=_ap_handler_init,
                             initargs=[self.qIn, self.qOut],
                             #initargs=[self.qIn, self.qOut, self.settings],
                             # Important to re-fill pool after
                             # terminating some child processes!
                             # Mabye not needed in 'spawn'-context
                             maxtasksperchild=1
                            )
            signal.signal(signal.SIGINT, original_sigint_handler)
        else:
            # Hm, this hangs sometimes :-(
            self.pool = get_context("spawn").\
                    Pool(processes=self.processes,
                         initializer=_ap_handler_init,
                         initargs=[self.qIn, self.qOut],
                         # initargs=[self.qIn, self.qOut, self.settings],
                         # Important to re-fill pool after
                         # terminating some child processes!
                         # Mabye not needed in 'spawn'-context
                         maxtasksperchild=1
                        )
        self._state = ActionPoolState.STARTED

        logger.info("ActionPool started")

    def stop(self):
        if self._state not in [ActionPoolState.STARTED]:
            logger.error("Pool is not started.")
            return

        self.pool.close()
        self.fetch_started_ids()  # clears qOut
        self._state = ActionPoolState.STOPED

        # Without this, child processes of workers
        # will survive deconstruction of this object.
        self.wait(timeout=1.0, terminate_workers=True)

        # Docs: 'joining process that uses queues needs to
        #        read all data before .join() is called.
        #        Otherwise .join() will block'
        #
        # NOTE: Well, reading all data is not a sufficient
        #       condition but required.
        #       Thus we need still pool.terminate() before pool.join()!
        #       The call of _close_queues() is just for generating
        #       log messages for debugging.
        self._close_queues()

        # This terminating resolves hanging pool.join()
        self.pool.terminate()
        self.pool.join()
        logger.info("ActionPool stoped")


    def push_action(self, f, args=()):
        #self.fetch_started_ids()

        # Gen id for this action
        rid = next(self._next_result_id)


        # NOTE: _num_active_or_pending <= len(self.pool._cache),
        # and not equal if we killed a process and didn't handled their
        # results/remove it from _cache by hand (?!)

        # Kill old open jobs if no space for more is left
        if self._num_active_or_pending >= self.max_active_or_pending:
            logger.debug("Start cleanup for {} pending "
                  "actions".format(self._num_active_or_pending))
            self.kill_stale_actions()

        # Re-check if space is available
        if self._num_active_or_pending >= self.max_active_or_pending:
            logger.debug("Cannot start new action. Still {} "
                         "pending".format(self._num_active_or_pending))
            self._counter_skipped.append(rid)
            return False

        # Put input arguments of action into Queue.
        logger.debug("Put rid={} in qIn".format(rid))
        self.qIn.put_nowait((rid, f, args))


        def action_succeded(t):
            mp_logger.debug("Action handler finished.")
            exitcode, rid, err, ret = t

            # Following leads to 'RuntimeError: dictionary changed size ...'
            # if not locked because this function is called from another thread
            self._pending_lock.acquire()
            self._pending.pop(rid, None)
            self._num_active_or_pending -= 1
            self._pending_lock.release()

            if exitcode == 0:
                self._counter_ok.append(rid)
            else:
                self._counter_failed.append(rid)
                mp_logger.error("Action handler error: {}".format(err))

            # Take (at least) this entry from qOut.
            self.fetch_started_ids()

        def action_failed(t):
            # Due try-catch construction in _ap_handler it will not
            # reached if the action (=f) failed.
            # Nevertheless this will be called if the process is
            # killed by c.terminate()
            mp_logger.debug("_ap_handler failed. Reason: {}".format(t))
            return

        # Add action into pool (as argument for '_ap_handler')
        # NOTE: We can not give 'rid' as argument to _ap_handler
        #       because the reading order of the queue can be scrambled.
        #       Thus we need to read this value from qIn.
        result = self.pool.apply_async(
            _ap_handler, args=(),
            callback=action_succeded,
            error_callback=action_failed)

        self._pending_lock.acquire()
        self._pending[rid] = Pending(None, result, None)
        self._num_active_or_pending += 1
        self._pending_lock.release()
        # Values for None-fields will be put in queue
        # if action-processes starts. Currently, they are unknown.

        return True

    def running_time_exceeded(self, start_time):
        return (time() - start_time > self.allow_abort_after)

    def fetch_started_ids(self):
        # Check which processes had alreaded started
        # and filled the queue

        while False:
            try:
                (rid, f, args) = self.qIn.get_nowait()
                logger.debug("\t\t\tHey, qIn not empty: {} {}".format(rid, f))
            except Empty:
                break

        while True:
            try:
                [rid, pid, time] = self.qOut.get_nowait()
                # [rid, pid, time] = self.qOut.get(block=True, timeout=0.1)
            except Empty:
                break

            pend = self._pending.get(rid)
            if pend:
                self._pending_lock.acquire()
                self._pending[rid] = pend._replace(pid=pid, time=time)
                self._pending_lock.release()
            else:
                # Do not update entry because this action was
                # already finished and action_succeded() had removed
                # the entry from _pending
                pass

    def kill_stale_actions(self, number_to_kill=1):
        self.fetch_started_ids()  # Check for new timestamps

        if number_to_kill <= 0:
            return

        to_remove = []
        self._pending_lock.acquire()
        _pending_copy = self._pending.copy()
        self._pending_lock.release()

        for rid,pend in _pending_copy.items():
            if pend.time is None:
                # This actions did not has started => no start time
                # available
                continue

            if self.running_time_exceeded(pend.time):
                # Find process for this pid
                for c in self.pool._pool:
                    # print(pend.pid, c.pid)
                    # Note that only N_PROCESSES different values for c.pid
                    # are possible.
                    # We assuming here that only one entry in _pending will match
                    # because earlier processes are already removed from this dict.
                    if c.pid == pend.pid:
                        to_remove.append((rid,c))
                        number_to_kill -= 1
                        break

            if number_to_kill <= 0:
                break

        if to_remove:
            # logger.debug("\t\t\tLen active_children A: {}".\
            #        format(len(self.pool._pool)))
            pass

        for (rid,c) in to_remove:
            # Terminates children created by subprocess.Popen
            kill_children(c.pid, False)

            # Now terminate process
            logger.debug("Send SIGTERM to {}".format(c.pid))
            if c.exitcode is None:
                c.terminate()

            if c.is_alive():
                try:
                    c.join(timeout=1.0)
                except TimeoutError:
                    logger.debug("Joining failed")
                    pass

            if c.exitcode is None:
                logger.debug("Send SIGKILL to {}".format(c.pid))
                c.kill()

            self._pending_lock.acquire()
            pend = self._pending.pop(rid, None)
            if pend:
                self._num_active_or_pending -= 1
                self._counter_aborted.append(rid)
                # Remove result from pool._cache
                try:
                    # Hm, wrong thread?! Sometimes it is already removed from _cache
                    pend.result._set(0, (False, TimeoutError("Stale action")))
                except KeyError:
                    pass

            self._pending_lock.release()

        if to_remove:
            # logger.debug("\t\t\tLen active_children B: {}".\
            #        format(len(self.pool._pool)))
            self.pool._repopulate_pool()  # Hm, does not hold len(_pool) constant
            # logger.debug("\t\t\tLen active_children C: {}".\
            #        format(len(self.pool._pool)))

    def wait_debug(self):
        n = 0
        while len(self.pool._cache) > 0:
            sleep(1.0)
            print(".", self.pool._cache.keys(),
                  "|", self._num_active_or_pending,
                  "P", len(self.pool._pool),
                  end="\n")
            self.kill_stale_actions(self._num_active_or_pending)
            n += 1
            if( n%5 == 0): print("")

    def wait(self, timeout=None, terminate_workers=False):
        """ Give each pending action the guaranteed running time
            but kill them if they are not fast enough.
            (Thus duration(self.wait()) <= duration(self.pool.join())

            Note/TODO: High ALLOW_ABORT_AFTER could leads to a very long
                       blocking.
        """

        if timeout is not None:
            end_time = time() + timeout

        abort_loop = 1000  # Just as fallback

        while self._num_active_or_pending > 0 or abort_loop == 0:
            abort_loop -= 1
            # Waiting on first process. (Return of others ignored here)
            result = next(iter(self.pool._cache.values()))
            wait_time = self.allow_abort_after
            if timeout is not None:
                wait_time = min(wait_time, end_time-time())
            if wait_time <= 0:
                logger.debug("ActionPool.wait() reached timeout")
                break
            try:
                result.get(wait_time)
            except TimeoutError:
                pass

            self.kill_stale_actions(self._num_active_or_pending)

        if timeout is not None and terminate_workers:
            self.kill_workers()
        if abort_loop == 0:
            raise RuntimeError("Some processes still running?!")


    def kill_workers(self):
        for c in self.pool._pool:
            # Terminates children created by subprocess.Popen
            kill_children(c.pid, False)

            if c.exitcode is None:
                c.terminate()
            try:
                c.join(timeout=1.0)
            except TimeoutError:
                pass
            if c.exitcode is None:
                c.kill()

    def statistic(self):
        # Due usage of multiprocessing.queues.SimpleQueue
        # and other problems it is hard do count the running
        # task. Just assume that all self.processes
        # will be used all the time.
        num_active = min(len(self.pool._cache),self.processes)

        return (" Tasks        ok: {}\n"
                " Tasks   skipped: {}\n"
                " Tasks   aborted: {}\n"
                " Tasks    failed: {}\n"
                "#Tasks    active: {}\n"
                "#Tasks not begun: {}".format(
                    self._counter_ok,
                    self._counter_skipped,
                    self._counter_aborted,
                    self._counter_failed,
                    num_active,
                    self._num_active_or_pending - num_active,
                ))

'''
class _pickable_settings:
    # Note: This modulel does NOT contain:
    #    FAVORITES, HISTORY, USER_FAVORITES, USER_HISTORY

    def __init__(self, settings=None):
        if settings:
            self.__setstate__(settings.__dict__)

    def __getstate__(self):
        return self.__dict__

    def __setstate__(self, state):
        #Types = (str, int, float, bytes, type(None), Feed)
        Types = (str, int, float, bytes, type(None))
        for (k,v) in state.items():
            if k.startswith("_"):
                continue

            if isinstance(v, Types):
                setattr(self, k, v)

            elif isinstance(v, list):
                # Allowed if all values of list in Types
                try:
                    next(filter(lambda x:not isinstance(x,Types), v))
                    continue
                except StopIteration:
                    setattr(self, k, v)

            elif isinstance(v, dict):
                # Allowed if all keys and values of dict in Types
                try:
                    next(filter(lambda x:not isinstance(x,Types), v.keys()))
                    continue
                except StopIteration:
                    pass
                try:
                    next(filter(lambda x:not isinstance(x,Types), v.values()))
                    continue
                except StopIteration:
                    setattr(self, k, v)
'''

# For actions.py

PopenArgs = namedtuple('PopenArgs', ['cmd'])
FwithArgs = namedtuple('FwithArgs', ['f', 'args'])
class PickableAction:
    def __init__(self, *operations):
        for op in operations:
            if isinstance(op, PopenArgs):
                continue
            if isinstance(op, FwithArgs):
                if callable(op.f) and globals()[op.f.__name__] == op.f:
                    continue  # ok, it is a global function
            raise Exception("Non-pickable operation detected. Input: {}".\
                           format(operations))
        self.operations = operations

def worker_handler(pickable_action):
    def callF(op):
        print("Call {}({})".format(
            op.f.__name__,
            ",".join([str(a) for a in op.args])))
        op.f(*op.args)

    def callPopen(op):
        print("Call {}".format(op.cmd))
        nullsink = open(os.devnull, 'w')
        nullsource = open(os.devnull, 'r')
        proc = Popen(op.cmd, stdin=nullsource,
                     stdout=nullsink, stderr=nullsink)
        # TODO: Could block eternal. Timeout + error handling would be nice
        proc.wait()

    for op in pickable_action.operations:
        if isinstance(op, PopenArgs):
            callPopen(op)
        if isinstance(op, FwithArgs):
            callF(op)


# Define some example functions
# Needs to be on module level to satisfy multiprocess's Pickler
def _i_am_fine():
    mp_logger.info("\t\tFirst function")
    sleep(_i_am_fine.duration)
_i_am_fine.duration = 3.0

def _i_throw_an_error():
    mp_logger.info("\t\tSecond function")
    x = 1/0
    sleep(2 * ALLOW_ABORT_AFTER)

def _i_am_too_slow():
    mp_logger.info("\t\tThird function")
    sleep(2 * ALLOW_ABORT_AFTER)

def _i_am_fine_too(arg1, arg2):
    mp_logger.info("\t\tForth function with args {} {}".format(arg1, arg2))
    sleep(1.0)

def _i_block():
    mp_logger.info("\t\tFifth function")
    sleep(1E4)


def example_usage():
    N_PROCESSES = 1
    MAX_ACTIVE_OR_PENDING = 3
    ALLOW_ABORT_AFTER = 2.0

    # This example sends five actions into a pool with
    # one worker-process and maximal 3 pending actions (incl. #workers)
    # • First action returns fast
    # • Second action fails
    # • Third action sleeps too long
    # • Forth action will not be added due full queue
    # • Fifth action will added (after some delay), but aborted
    #   due programm end.
    #
    # Note that duration of first action is > ALLOW_ABORT_AFTER, but
    # if we add the forth action the duration limit was not already reached.
    #

    with ActionPool(settings=None,
                    processes=N_PROCESSES,
                    max_active_or_pending=MAX_ACTIVE_OR_PENDING,
                    allow_abort_after=ALLOW_ABORT_AFTER
                   ) as ap:
        # ap.start() # not needed in 'with'-statement

        args = ()
        for s in range(4):
            #print(ap.statistic())
            ap.push_action(_i_am_fine, args)
            #print(ap.statistic())
            ap.push_action(_i_throw_an_error, args)
            #print(ap.statistic())
            ap.push_action(_i_am_too_slow, args)
            #print(ap.statistic())
            print("=======")
            # this forth  action will not start because max_active_or_pending = 3
            # and at least above three are still running
            ap.push_action(_i_am_fine_too, (4,"arg2"))

            # Now give processes some time. If we immideatly push more
            # actions, push_action will fail because
            # MAX_ACTIVE_OR_PENDING is reached.
            #print(ap.statistic())
            sleep(_i_am_fine.duration + 1.0)
            ap.push_action(_i_block)

            ap.wait(5.0)  # To clear pending task before next loop begins

        print("======================")

        # Waiting until every pending task was at least started
        print("Waiting until pool finishs its tasks")
        ap.wait_debug()

        ap.fetch_started_ids()
        # Finally print statistic before ap will be released
        print(ap.statistic())

        # ap.stop() # not needed in 'with'-statement

    # Now, ap' deconstructor was called.
    print("End")


def example_spawn_app():
    cmd = ("mimeopen", "test.txt")
    open_text_editor = PickableAction(PopenArgs(cmd))

    with ActionPool(settings=None,
                    processes=1,
                    max_active_or_pending=1,
                    allow_abort_after=10.0,
                   ) as ap:
        ap.push_action(worker_handler, args=(open_text_editor,))

        # Give worker process some time to react.
        sleep(2.0)

        print("Wait until task ends or timeout is reached.")
        ap.wait(10.0)

        # Leaving with will invoke ap.stop()



# Setup worker process logging
# due spawn-context defined on module level.
if __name__ == '__main__':
    mp_logger = log_to_stderr()
    mp_logger.setLevel(logging.DEBUG)
    mp_logger.addFilter(JustThisFileFilter())

    # fork-Method does not work! Somehow I've added a racing condition,
    # see https://pythonspeed.com/articles/python-multiprocessing/
    set_start_method("spawn")


if __name__ == '__main__':

    # Setup logger of this process
    logging.basicConfig(level=logging.DEBUG)
    # logger.setLevel(logging.DEBUG)

    example_usage()
    # example_spawn_app()


