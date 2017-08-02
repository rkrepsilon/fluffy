import sys
import os
import yaml
import atexit
from collections import OrderedDict
from threading import Timer, Lock

from .addressbook import AddressBook
from .interfaces import Interfaces
from .chains import Chains
from .rules import Rules
from .services import Services
from .checks import Checks
from .sessions import Sessions

import logging
logger = logging.getLogger(__name__)


class Fluffy(object):
    def __init__(self, data_dir, max_sessions):
        self.addressbook = AddressBook.load_yaml(
            db=os.path.join(data_dir, 'addressbook.db'))
        self.interfaces = Interfaces.load_yaml(
            db=os.path.join(data_dir, 'interfaces.db'))
        self.chains = Chains.load_yaml(db=os.path.join(data_dir, 'chains.db'))
        self.services = Services.load_yaml(
            db=os.path.join(data_dir, 'services.db'))
        self.checks = Checks.load_yaml(
            db=os.path.join(data_dir, 'checks.db'))
        self.rules = Rules.load_yaml(db=os.path.join(data_dir, 'rules.db'), addressbook=self.addressbook,
                                     interfaces=self.interfaces, chains=self.chains, services=self.services)

        self._data_dir = data_dir
        self._max_sessions = max_sessions

        # create data directory
        if not os.path.exists(self._data_dir):
            logger.info("Creating data directory ({})".format(self._data_dir))
            try:
                os.makedirs(self._data_dir)
            except Exception as e:
                logger.exception("Failed to create data directory")
                sys.exit(1)

        # configuration sessions
        self.sessions = Sessions(rules=self.rules, checks=self.checks, data_dir=self._data_dir,
                                 max_sessions=self._max_sessions)

        # persist data every 5m
        logger.debug("Scheduling configuration flush timer")
        self._flush_lock = Lock()
        self._flush_timer = Timer(60, self._async_flush)
        self._flush_timer.daemon = True
        self._flush_timer.start()

        # register exit function
        atexit.register(self._exit)

        # load active rules
        self.load()

    @classmethod
    def load_yaml(cls, config_file):
        config_dir = os.path.dirname(config_file)

        config = {
            'data_dir': '/var/lib/fluffy',
            'max_sessions': 10
        }

        try:
            with open(config_file, 'r') as stream:
                config.update(yaml.load(stream))
        except:
            logger.exception("Failed to load configuration file")
            sys.exit(1)

        return cls(**config)

    def load(self):
        try:
            session = self.sessions.add(name='startup')
            if session.test():
                session.commit(force=True, rollback=False,
                               rollback_interval=None)
            else:
                raise RuntimeError("Configuration test failed")
            self.sessions.delete(name='startup')
        except:
            logger.exception("Failed to load startup configuration")
            sys.exit(1)

    def flush(self):
        with self._flush_lock:
            self.addressbook.save()
            self.interfaces.save()
            self.chains.save()
            self.rules.save()
            self.services.save()
            self.checks.save()

    def _async_flush(self):
        logger.debug("Flushing configuration")
        self.flush()
        logger.debug("Re-scheduling configuration flush timer")
        self._flush_timer = Timer(60, self._async_flush)
        self._flush_timer.daemon = True
        self._flush_timer.start()

    def _exit(self):
        logger.info("Shutdown in progress - flushing configuration")
        self.flush()
        logger.debug("Canceling configuration flush timer")
        if self._flush_timer:
            self._flush_timer.cancel()
