import hashlib
import hmac
import secrets


def new_seed():
    return secrets.token_hex(32)


def commitment(seed):
    return hashlib.sha256(seed.encode()).hexdigest()


class FairRandom:
    """Reproducible HMAC-SHA256 stream: clientSeed:nonce:cursor, first 52 bits."""
    def __init__(self, server_seed, client_seed, nonce):
        self.seed, self.client, self.nonce, self.cursor = server_seed, client_seed, nonce, 0

    def draw(self):
        message = f'{self.client}:{self.nonce}:{self.cursor}'.encode()
        digest = hmac.new(self.seed.encode(), message, hashlib.sha256).hexdigest()
        self.cursor += 1
        return int(digest[:13], 16) / 2**52

    def pick(self, pool):
        return pool.pop(int(self.draw() * len(pool)))
