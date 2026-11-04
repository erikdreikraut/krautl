"""Unattended worker entrypoint with bounded local diagnostic logs."""
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys

class LogStream:
    def __init__(self, logger):
        self.logger=logger
        self.buffer=''
    def write(self, text):
        self.buffer+=text
        while '\n' in self.buffer:
            line,self.buffer=self.buffer.split('\n',1)
            if line:self.logger.info(line)
        return len(text)
    def flush(self):
        if self.buffer:self.logger.info(self.buffer);self.buffer=''


def main():
    root=Path('C:/Krautl-Bilddienst')
    sys.path.insert(0,str(root))
    log=logging.getLogger('bilddienst')
    log.setLevel(logging.INFO)
    handler=RotatingFileHandler(root/'bilddienst.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')
    handler.setFormatter(logging.Formatter('%(asctime)s %(message)s'))
    log.addHandler(handler)
    sys.stdout=sys.stderr=LogStream(log)
    log.info('Bilddienst im Hintergrund gestartet.')
    try:
        from bridge.worker import main as worker_main
        sys.argv=['bridge.worker','--config',str(root/'bridge/config.json')]
        worker_main()
    except Exception as exc:
        # Avoid exception tracebacks that may contain SQL connection credentials.
        log.error('Bilddienst beendet: %s',str(exc) if type(exc) is ValueError else type(exc).__name__)
        return 1
    finally:
        sys.stdout.flush()
    return 0

if __name__=='__main__':
    raise SystemExit(main())
