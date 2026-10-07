import hashlib

from django.contrib.auth.hashers import BasePasswordHasher, mask_hash
from django.utils.crypto import constant_time_compare


class LegacySHA256PasswordHasher(BasePasswordHasher):
    """Verifica hash-urile SHA-256 nesarate din vechea aplicatie Firebase.

    Stocat ca `legacy_sha256$$<hex>`. `must_update` intoarce True, deci Django
    inlocuieste hash-ul cu PBKDF2 la primul login reusit.
    """

    algorithm = 'legacy_sha256'

    def salt(self):
        return ''

    def encode(self, password, salt=''):
        return f'{self.algorithm}$${hashlib.sha256(password.encode()).hexdigest()}'

    def decode(self, encoded):
        algorithm, _empty, digest = encoded.split('$', 2)
        return {'algorithm': algorithm, 'hash': digest, 'salt': ''}

    def verify(self, password, encoded):
        return constant_time_compare(self.encode(password), encoded)

    def safe_summary(self, encoded):
        return {'algorithm': self.algorithm, 'hash': mask_hash(self.decode(encoded)['hash'])}

    def must_update(self, encoded):
        return True

    def harden_runtime(self, password, encoded):
        pass
