#! /usr/bin/env python3
""" Pop records from queue and apply action. If action throws error,
put record back on queue.
"""

# Probably could use asyncio to good use here.  Didn't know about it
# when I started and maybe our case is easy enuf that it doesn't
# matter. But we do a loop (while True) that smacks of an event loop!!!


import argparse
import logging
import json
import time
import sys

import redis

from . import config
from . import dqutils
from . import default_config
from .dbvars import *
from .actions import *

# GROSS: highly nested code!!!
def process_queue_forever(qname, qcfg, dirs, delay=1.0):
    'Block waiting for items on queue, then process, repeat.'
    red = redis.StrictRedis()
    action_name = qcfg[qname]['action_name']
    action = action_lut[action_name]
    maxerrors = qcfg[qname]['maximum_errors_per_record']

    logging.debug('Read Queue "{}"'.format(qname))
    while True: # pop from queue forever
        #! logging.debug('Read Queue: loop')

        if red.get(actionP) == b'off':
            time.sleep(delay)
            continue

        # ALERT: being "clever" here!
        #
        # If actionP was turned on, and the queue isn't being filled,
        # we will eventually pop everything from the queue and block.
        # But then if actionP is turned OFF, we don't know yet because
        # we are still blocking.  So next queue item will sneak by.
        # Probably unimportant on long running system, but plays havoc
        # with testing. To resolve, on setting actionP to off, we push
        # to dummy to clear block.
        (keynameB, ridB) = red.brpop([dummy, aq]) # BLOCKING pop (over key list)
        if keynameB.decode() == dummy:
            continue
        rid = ridB.decode()
        #!logging.debug('Read Queue: got something')

        # buffer all commands done by pipeline, make command list atomic
        with red.pipeline() as pl:
            while True: # retry of clients collide on watched variables
                try:
                    pl.watch(aq, aqs, rids, ecnt, iq, rid)
                    rec = dqutils.decode_dict(pl.hgetall(rid))

                    # switch to normal pipeline mode where commands get buffered
                    pl.multi()

                    pl.srem(aqs, rid)
                    logging.debug('Run action: "%s"(%s)"'%(action_name, rec))
                    try:
                        result = action(rec, qcfg=qcfg, dirs=dirs)
                        logging.debug('DONE action: "{}" => {}'
                                      .format(action_name, result))
                    except Exception as ex:
                        pl.hincrby(ecnt, rid)

                        # pl.hget() returns StrictPipeline; NOT value of key!
                        # use of RED here causes us to not get incremented value
                        ercnt = int(red.hget(ecnt,rid)) + 1 

                        erall = red.hgetall(ecnt)
                        logging.debug('Got error on action. ercnt={}'
                                      .format(ercnt))
                        #!cnt = 0 if ercnt == None else ercnt
                        cnt = ercnt
                        logging.debug('Error(#{}) running action "{}"'
                                      .format(cnt, action_name))
                        if cnt > maxerrors:
                            msg = ('Failed to run action "{}" {} times. '
                                   +' Max allowed is {} so moving it to the'
                                   +' INACTIVE queue.'
                                   +' Record={}. Exception={}')
                            logging.error(msg.format(action_name,
                                                     cnt, maxerrors, rec, ex))
                            # action kept failing: move to Inactive queue
                            pl.lpush(iq, rid)  
                            # Person should monitor INACTIVE queue!!!
                        else:
                            msg = ('Failed to run action "{}" {} times. '
                                   +' Max allowed is {} so will try again'
                                   +' later.'
                                   +' Record={}. Exception={}')
                            logging.error(msg.format(action_name,
                                                     cnt, maxerrors, rec, ex))
                            # failed: go to the end of the line
                            pl.lpush(aq, rid) 
                    else:
                        # action did not raise exception
                        msg = ('Action "{}" ran successfully against ({}):'
                               +' {} => {}')
                        logging.info(msg.format(action_name, rid, rec, result))
                        pl.srem(rids, rid)
                    pl.save()
                    pl.execute() # execute the pipeline
                    break
                except redis.WatchError:
                    # another client must have changed  watched vars between
                    # the time we started WATCHing them and the pipeline's
                    # execution. Our best bet is to just retry.
                    continue # while True

##############################################################################


def main():
    'Parse args, then start reading queue forever.'
    possible_qnames = ['transfer', 'submit', 'mitigate']
    parser = argparse.ArgumentParser(
        description='Data Queue service',
        epilog='EXAMPLE: %(prog)s --loglevel DEBUG &'
        )

    #!parser.add_argument('--host',
    #!                    help='Host to bind to',
    #!                    default='localhost')
    #!parser.add_argument('--port',
    #!                    help='Port to bind to',
    #!                    type=int, default=9988)
    parser.add_argument('--cfg',
                        help='Configuration file (json format)',
                        type=argparse.FileType('r'))
    parser.add_argument('--queue', '-q',
                        choices=possible_qnames,
                        help='Name of queue to pop from. Must be in cfg file.')

    parser.add_argument('--loglevel',
                        help='Kind of diagnostic output',
                        choices=['CRTICAL', 'ERROR', 'WARNING',
                                 'INFO', 'DEBUG'],
                        default='WARNING')
    args = parser.parse_args()

    log_level = getattr(logging, args.loglevel.upper(), None)
    if not isinstance(log_level, int):
        parser.error('Invalid log level: %s' % args.loglevel)
    logging.basicConfig(level=log_level,
                        format='%(levelname)s %(message)s',
                        datefmt='%m-%d %H:%M')
    logging.debug('Debug output is enabled!!')
    ###########################################################################


    #!cfg = default_config.DQ_CONFIG if args.cfg is None else json.load(args.cfg)
    #!qcfg = dqutils.get_config_lut(cfg)[args.queue]
    qcfg, dirs = config.get_config(possible_qnames)

    dqutils.save_pid(sys.argv[0], piddir=dirs['run_dir'])

    # red = redis.StrictRedis(host=args.host, port=args.port)
    #! process_queue_forever(red, config)
    process_queue_forever(args.queue, qcfg, dirs)

if __name__ == '__main__':
    main()

    