#! /usr/bin/python3
# This script exercises the c-lightning implementation

# Released by Rusty Russell under CC0:
# https://creativecommons.org/publicdomain/zero/1.0/

import bitcoin
import bitcoin.rpc
import importlib
import lightning
import os
import shutil
import struct
import subprocess
import tempfile
import time

from concurrent import futures
from ephemeral_port_reserve import reserve

test = importlib.import_module('test-events')

TIMEOUT = int(os.getenv("TIMEOUT", "30"))
LIGHTNING_SRC = os.getenv("LIGHTNING_SRC", '../lightning/')


def wait_for(success, timeout=TIMEOUT):
    start_time = time.time()
    interval = 0.25
    while not success() and time.time() < start_time + timeout:
        time.sleep(interval)
        interval *= 2
        if interval > 5:
            interval = 5
    return time.time() <= start_time + timeout


# Stolen from lightning/tests/utils.py
class SimpleBitcoinProxy:
    """Wrapper for BitcoinProxy to reconnect.

    Long wait times between calls to the Bitcoin RPC could result in
    `bitcoind` closing the connection, so here we just create
    throwaway connections. This is easier than to reach into the RPC
    library to close, reopen and reauth upon failure.
    """
    def __init__(self, btc_conf_file, *args, **kwargs):
        self.__btc_conf_file__ = btc_conf_file

    def __getattr__(self, name):
        if name.startswith('__') and name.endswith('__'):
            # Python internal stuff
            raise AttributeError

        # Create a callable to do the actual call
        proxy = bitcoin.rpc.RawProxy(btc_conf_file=self.__btc_conf_file__)

        def f(*args):
            return proxy._call(name, *args)

        # Make debuggers show <function bitcoin.rpc.name> rather than <function
        # bitcoin.rpc.<lambda>>
        f.__name__ = name
        return f


class Bitcoind(object):
    """Starts regtest bitcoind on an ephemeral port, and returns the RPC proxy"""
    def __init__(self, basedir):
        self.bitcoin_dir = os.path.join(basedir, "bitcoind")
        if not os.path.exists(self.bitcoin_dir):
            os.makedirs(self.bitcoin_dir)
        self.bitcoin_conf = os.path.join(self.bitcoin_dir, 'bitcoin.conf')
        self.cmd_line = [
            'bitcoind',
            '-datadir={}'.format(self.bitcoin_dir),
            '-server',
            '-regtest',
            '-logtimestamps',
            '-nolisten']
        self.port = reserve()
        print("Port is {}, dir is {}".format(self.port, self.bitcoin_dir))
        # For after 0.16.1 (eg. 3f398d7a17f136cd4a67998406ca41a124ae2966), this
        # needs its own [regtest] section.
        with open(self.bitcoin_conf, 'w') as f:
            f.write("regtest=1\n")
            f.write("rpcuser=rpcuser\n")
            f.write("rpcpassword=rpcpass\n")
            f.write("[regtest]\n")
            f.write("rpcport={}\n".format(self.port))
        self.rpc = SimpleBitcoinProxy(btc_conf_file=self.bitcoin_conf)

    def start(self):
        self.proc = subprocess.Popen(self.cmd_line, stdout=subprocess.PIPE)

        # Wait for it to startup.
        while b'Done loading' not in self.proc.stdout.readline():
            pass

        # Block #1.
        self.rpc.submitblock('0000002006226e46111a0b59caaf126043eb5bbf28c34f3a5e332a1fc7b2b73cf188910f7b8705087f9bddd2777021d2a1dfefc2f1c5afa833b5c4ab00ccc8a556d04283f5a1095dffff7f200100000001020000000001010000000000000000000000000000000000000000000000000000000000000000ffffffff03510101ffffffff0200f2052a01000000160014751e76e8199196d454941c45d1b3a323f1433bd60000000000000000266a24aa21a9ede2f61c3f71d1defd3fa999dfa36953755c690689799962b48bebd836974e8cf90120000000000000000000000000000000000000000000000000000000000000000000000000')
        self.rpc.generatetoaddress(100, self.rpc.getnewaddress())


    def stop(self):
        self.proc.kill()

    def restart(self):
        # Only restart if we have to.
        if self.rpc.getblockcount() != 102 or self.rpc.getrawmempool() == []:
            self.stop()
            shutil.rmtree(os.path.join(self.bitcoin_dir, 'regtest'))
            self.start()


class CLightningRunner(object):
    def __init__(self, args):
        self.connections = []
        directory = tempfile.mkdtemp(prefix='test-events-')
        self.bitcoind = Bitcoind(directory)
        self.bitcoind.start()
        self.executor = futures.ThreadPoolExecutor(max_workers=20)

        self.lightning_dir = os.path.join(directory, "lightningd")
        if not os.path.exists(self.lightning_dir):
            os.makedirs(self.lightning_dir)
        self.lightning_port = reserve()

        self.startup_flags = []
        for flag in args.startup_flags:
            self.startup_flags.append("--{}".format(flag))

    def start(self):
        self.proc = subprocess.Popen(['{}/lightningd/lightningd'.format(LIGHTNING_SRC),
                                      '--lightning-dir={}'.format(self.lightning_dir),
                                      '--funding-confirms=3',
                                      '--dev-force-privkey=0000000000000000000000000000000000000000000000000000000000000001',
                                      '--dev-force-bip32-seed=0000000000000000000000000000000000000000000000000000000000000001',
                                      '--dev-force-channel-secrets=0000000000000000000000000000000000000000000000000000000000000010/0000000000000000000000000000000000000000000000000000000000000011/0000000000000000000000000000000000000000000000000000000000000012/0000000000000000000000000000000000000000000000000000000000000013/0000000000000000000000000000000000000000000000000000000000000014/FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF',
                                      '--dev-bitcoind-poll=1',
                                      '--dev-broadcast-interval=1000',
                                      '--bind-addr=127.0.0.1:{}'.format(self.lightning_port),
                                      '--network=regtest',
                                      '--bitcoin-rpcuser=rpcuser',
                                      '--bitcoin-rpcpassword=rpcpass',
                                      '--bitcoin-rpcport={}'.format(self.bitcoind.port),
                                      '--log-level=debug',
                                      '--log-file=log']
                                      + self.startup_flags)
        self.rpc = lightning.LightningRpc(os.path.join(self.lightning_dir, "lightning-rpc"))

        def node_ready(rpc):
            try:
                rpc.getinfo()
                return True
            except Exception:
                return False

        if not wait_for(lambda: node_ready(self.rpc)):
            raise subprocess.TimeoutExpired(self.proc,
                                            "Could not contact lightningd")

        # Make sure that we see any funds that come to our wallet
        for i in range(5):
            self.rpc.newaddr()


    def stop(self):
        self.rpc.stop()
        self.bitcoind.stop()
        for c in self.connections:
            c.proc.kill()

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, type, value, tb):
        self.stop()

    def restart(self):
        self.rpc.stop()
        self.bitcoind.restart()
        for c in self.connections:
            c.proc.kill()

        # Make a clean start
        os.remove(os.path.join(self.lightning_dir, "gossip_store"))
        os.remove(os.path.join(self.lightning_dir, "lightningd.sqlite3"))
        os.remove(os.path.join(self.lightning_dir, "log"))
        self.start()

    def connect(self, conn, line):
        # FIXME: Open-code the lightning enc protocol in Python!
        conn.proc = subprocess.Popen(['{}/devtools/gossipwith'.format(LIGHTNING_SRC),
                                      '--privkey={}'.format(conn.connkey),
                                      '--stdin',
                                      '--no-init',
                                      '0279be667ef9dcbbac55a06295ce870b07029bfcdb2dce28d959f2815b16f81798@localhost:{}'.format(self.lightning_port)],
                                     stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE,
                                     bufsize=0)

    def getblockheight(self):
        return self.bitcoind.rpc.getblockcount()

    def trim_blocks(self, newheight):
        h = self.bitcoind.rpc.getblockhash(newheight + 1)
        self.bitcoind.rpc.invalidateblock(h)

    def add_blocks(self, txs, n, line):
        for tx in txs:
            self.bitcoind.rpc.sendrawtransaction(tx)
        self.bitcoind.rpc.generatetoaddress(n, self.bitcoind.rpc.getnewaddress())

        if not wait_for(lambda: self.rpc.getinfo()['blockheight'] == self.getblockheight()):
            raise test.ValidationError(line,
                                       "Node did not sync to blockheight:"
                                       " {} vs {}"
                                       .format(self.rpc.getinfo()['blockheight'],
                                               self.getblockheight()))

    def disconnect(self, conn, line):
        # FIXME: Inject a bad enc packet, so it hangs up on us *after*
        # processing
        time.sleep(1)
        conn.proc.terminate()
        conn.proc.wait(30)

    def recv(self, conn, outbuf, line):
        rawl = struct.pack('>H', len(outbuf))
        conn.proc.stdin.write(rawl)

        while len(outbuf) != 0:
            written = conn.proc.stdin.write(outbuf)
            outbuf = outbuf[written:]

    # FIXME: Implement fundchannel.
    # We'll need to import privkey into bitcoind and hand-generate the tx
    # then use fundchannel_start.

    def invoice(self, amount, preimage, line):
        self.rpc.invoice(msatoshi=amount,
                         label=str(line),
                         description='invoice from {}'.format(line),
                         preimage=preimage)

    def _readmsg(self, conn):
        rawl = conn.proc.stdout.read(2)
        length = struct.unpack('>H', rawl)[0]
        msg = bytes()
        while len(msg) < length:
            msg += conn.proc.stdout.read(length - len(msg))
        return msg

    def expect_send(self, conn, line, timeout=TIMEOUT):
        fut = self.executor.submit(self._readmsg, conn)
        try:
            return fut.result(timeout)
        except futures.TimeoutError:
            raise test.ValidationError(line, "Timed out")

    def wait_for_finalmsg(self, conn):
        # We told it to flush gossip every 1000msec, so give 2 seconds here.
        while True:
            fut = self.executor.submit(self._readmsg, conn)
            try:
                return fut.result(2)
            except futures.TimeoutError:
                return None

    def expect_tx(self, tx, line):
        def tx_in_mempool(tx):
            for txid in self.bitcoind.rpc.getrawmempool():
                if self.bitcoind.rpc.getrawtransaction(txid) == tx:
                    return True
            return False

        # This tx should appear in the mempool.
        if not wait_for(lambda: tx_in_mempool(tx)):
            raise test.ValidationError(line, "Did not broadcast the transaction")

    def expect_error(self, conn, line):
        while True:
            msg = self.expect_send(conn, line)

            # If we got an error, mark it
            if struct.unpack('>H', msg[0:2]) == (17,):
                return

    def final_error(self):
        # Just make sure it doesn't send an ERROR, but only give it 1 second.
        # FIXME: We should just use poll to see if any output pending!
        for c in self.connections:
            try:
                msg = self.expect_send(c, None, 1)
                # If we got an error, mark it
                if struct.unpack('>H', msg[0:2]) == (17,):
                    return msg.hex()
            except test.ValidationError:
                pass
        return None


if __name__ == "__main__":
    parser = test.setup_cmdline_options()
    args = parser.parse_args()
    # Here are the options we support.
    args.option += ['option_data_loss_protect/odd',
                    'option_initial_routing_sync/odd',
                    'option_upfront_shutdown_script/odd',
                    'option_gossip_queries/odd']

    # We use a context here, so we can always kill processes at exit
    with CLightningRunner(args) as runner:
        test.main(args, runner)
