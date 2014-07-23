#! /usr/bin/env python
'''\ 
Pop records from queue and apply action. 
'''

import os, sys, string, argparse, logging
import redis
import json
from dbvars import *
from actions import *


def process_queue_forever(r, cfg_file): 
    if cfg_file is None:
        cfg = dict(
            maximum_errors_per_record = 3, 
            action_name = "echo00",
            )
    else:
        cfg = json.load(cfg_file)
    action_name = cfg['action_name']
    action = action_lut[action_name]

    errorCnt = 0
    logging.debug('Process Queue')
    while True:
        if r.get(actionP) == b'off':
            continue

        (keynameB,ridB) = r.brpop([aq]) # BLOCKING pop (over list of keys)
        keyname = keynameB.decode()
        rid = ridB.decode()

        pl = r.pipeline()
        pl.watch(aq,aqs,rids,ecnt,iq,rid)
        pl.multi()

        pl.srem(aqs,rid) 
        rec = r.hgetall(rid)
        success = action(rec)
        if success:
            logging.debug('Action ran successfully against (%s): %s',
                          rid,rec)            
            pl.srem(rids,rid) 
        else:
            errorCnt += 1
            cnt = pl.hincrby(ecnt,rid)
            print('Error count for "%s"=%d'%(rid,cnt))
            if cnt > cfg['maximum_errors_per_record']:
                pl.lpush(iq,rid)  # kept failing: move to Inactive queue
                logging.warning(
                    ': Failed to run action "%s" on record (%s) %d times.'
                    +' Moving it to the Inactive queue',
                    action_name, rec,cnt)
            else:
                logging.error(
                    ': Failed to run action "%s" on record (%s) %d times',
                    action_name, rec, cnt)
                pl.lpush(aq,rid) # failed: got to the end of the line
        pl.save()    
        pl.execute()

##############################################################################


def main():
    #!print('EXECUTING: %s\n\n' % (string.join(sys.argv)))
    parser = argparse.ArgumentParser(
        description='Data Queue service',
        epilog='EXAMPLE: %(prog)s --loglevel DEBUG &'
        )

    parser.add_argument('--host',  help='Host to bind to',
                        default='localhost')
    parser.add_argument('--port',  help='Port to bind to',
                        type=int, default=9988)
    parser.add_argument('--cfg', 
                        help='Configuration file',
                        type=argparse.FileType('r') )


    parser.add_argument('--loglevel',      help='Kind of diagnostic output',
                        choices = ['CRTICAL','ERROR','WARNING','INFO','DEBUG'],
                        default='WARNING',
                        )
    args = parser.parse_args()

    log_level = getattr(logging, args.loglevel.upper(), None)
    if not isinstance(log_level, int):
        parser.error('Invalid log level: %s' % args.loglevel) 
    logging.basicConfig(level = log_level,
                        format='%(levelname)s %(message)s',
                        datefmt='%m-%d %H:%M'
                        )
    logging.debug('Debug output is enabled!!')
    ###########################################################################

    process_queue_forever(redis.StrictRedis(), args.cfg)

if __name__ == '__main__':
    main()
